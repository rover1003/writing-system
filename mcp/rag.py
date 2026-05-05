"""
RAG 模块 — 章节向量检索
- 调 Ollama nomic-embed-text 生成 768 维向量
- JSON 文件存储向量索引（零依赖）
- numpy-free cosine similarity（手写）
- 自动按章节号过滤，避免召回当前章节内容
"""
import os
import json
import hashlib
import math
import re
import logging
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger("mcp.rag")

# ── 配置 ────────────────────────────────────────────────────────────────────
OLLAMA_BASE = "http://localhost:11434"
EMBED_MODEL = "nomic-embed-text:latest"
EMBEDDING_DIM = 768
INDEX_FILE = Path(__file__).parent / "rag_index.json"
CHUNK_SIZE = 500  # 每块字符数
CHUNK_OVERLAP = 50  # 块重叠字符

# ── Ollama embedding ────────────────────────────────────────────────────────
def embed_texts(texts: list[str], timeout: float = 60.0) -> list[list[float]]:
    """调 Ollama 批量生成 embedding。失败抛异常。"""
    if not texts:
        return []
    try:
        embeddings = []
        for text in texts:
            resp = requests.post(
                f"{OLLAMA_BASE}/api/embeddings",
                json={"model": EMBED_MODEL, "prompt": text},
                timeout=timeout,
            )
            resp.raise_for_status()
            emb = resp.json().get("embedding", [])
            if len(emb) != EMBEDDING_DIM:
                raise ValueError(f"Expected {EMBEDDING_DIM} dims, got {len(emb)}")
            embeddings.append(emb)
        return embeddings
    except Exception as e:
        logger.error(f"Embedding failed: {e}")
        raise RuntimeError(f"Ollama embedding 调用失败: {e}")


# ── cosine similarity（纯 Python，无 numpy）─────────────────────────────────────
def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(ai * bi for ai, bi in zip(a, b))
    norm_a = math.sqrt(sum(ai * ai for ai in a))
    norm_b = math.sqrt(sum(bi * bi for bi in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


# ── 文本分块 ────────────────────────────────────────────────────────────────
def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """按字符数分块，保留段落边界。"""
    # 先按换行分割段落
    paragraphs = re.split(r"\n+", text)
    chunks = []
    current = ""

    for para in paragraphs:
        if len(current) + len(para) + 1 <= chunk_size:
            current += ("\n" if current else "") + para
        else:
            if current:
                chunks.append(current.strip())
            # 滚动窗口：从上一个块末尾取 overlap 字符作为新块开头（保持上下文连贯）
            current = current[-overlap:] + ("\n" if current[-overlap:] and current[-overlap] not in " \n\t" else "") + para

    if current.strip():
        chunks.append(current.strip())
    return [c for c in chunks if c]


# ── 索引结构 ────────────────────────────────────────────────────────────────
# {
#   "chunks": [
#     {
#       "id": "md5hash",
#       "chapter_num": 28,
#       "text": "...",
#       "embedding": [0.1, ...],
#       "tags": []
#     },
#     ...
#   ]
# }

def _compute_id(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()[:12]


def _extract_tags(text: str) -> list[str]:
    """从文本中粗略提取人物标签（减轻 prompt 负担）。"""
    # TODO: 可配置的人物标签列表，默认为空（由调用方注入）
    return []


# ── 核心 API ────────────────────────────────────────────────────────────────
def load_index() -> dict:
    """加载现有索引，不存在则返回空结构。"""
    if INDEX_FILE.exists():
        try:
            with open(INDEX_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"索引加载失败，创建新索引: {e}")
    return {"chunks": []}


def save_index(index: dict) -> None:
    """持久化索引到文件。"""
    INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = INDEX_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False)
    tmp.rename(INDEX_FILE)
    logger.info(f"索引已保存，共 {len(index['chunks'])} 个块")


def add_chunks(chunks: list[dict], overwrite: bool = True) -> int:
    """
    添加块到索引。
    chunks: [{"text": "...", "chapter_num": 28}, ...]
    返回新增块数。
    """
    index = load_index()
    existing_ids = {c["id"] for c in index["chunks"]} if not overwrite else set()
    added = 0

    for chunk in chunks:
        text = chunk["text"].strip()
        if not text:
            continue
        chunk_id = _compute_id(text)
        if chunk_id in existing_ids:
            continue

        # 生成 embedding
        try:
            embeddings = embed_texts([text])
            embedding = embeddings[0]
        except Exception as e:
            logger.warning(f"跳过块（embedding失败）: {text[:50]}... 错误: {e}")
            continue

        entry = {
            "id": chunk_id,
            "chapter_num": chunk.get("chapter_num", 0),
            "text": text,
            "embedding": embedding,
            "tags": _extract_tags(text),
        }
        index["chunks"].append(entry)
        added += 1

    if added > 0:
        save_index(index)
    return added


def index_chapter(chapter_num: int, chapter_text: str) -> int:
    """对章节正文分块并建索引（重建模式：删除旧块后重新加入）。"""
    # 1. 从索引中移除该章节所有旧块
    index = load_index()
    original_count = len(index["chunks"])
    index["chunks"] = [c for c in index["chunks"] if c.get("chapter_num") != chapter_num]
    removed = original_count - len(index["chunks"])
    if removed:
        save_index(index)
        logger.info(f"移除章节 {chapter_num} 的 {removed} 个旧块")

    # 2. 分块并重新加入
    chunks = chunk_text(chapter_text)
    chunk_dicts = [{"text": c, "chapter_num": chapter_num} for c in chunks]
    return add_chunks(chunk_dicts, overwrite=True)


def search(query: str, top_k: int = 5, exclude_chapter: int = None,
           tags: list[str] = None, timeout: float = 60.0) -> list[dict]:
    """
    语义检索最相关块。
    - exclude_chapter: 排除某章节（写新章节时避免召回正在写的内容）
    - tags: 优先命中包含这些标签的块
    返回 top_k 个结果，每项含 text / chapter_num / score / tags
    """
    try:
        query_embs = embed_texts([query], timeout=timeout)
        query_emb = query_embs[0]
    except Exception as e:
        logger.warning(f"Query embedding failed: {e}")
        return []

    index = load_index()
    candidates = []

    for chunk in index["chunks"]:
        # 排除指定章节
        if exclude_chapter is not None and chunk.get("chapter_num") == exclude_chapter:
            continue
        # 标签过滤
        if tags:
            chunk_tags = set(chunk.get("tags", []))
            if not chunk_tags.intersection(tags):
                continue

        score = _cosine(query_emb, chunk["embedding"])
        candidates.append({
            "text": chunk["text"],
            "chapter_num": chunk.get("chapter_num", 0),
            "score": round(score, 4),
            "tags": chunk.get("tags", []),
        })

    # 排序取 top_k
    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates[:top_k]


def build_index_from_chapters(chapters_dir: Path, start_chapter: int = 1,
                               end_chapter: int = 29) -> dict:
    """
    批量为现有章节建索引。
    返回统计信息。
    """
    stats = {"chapters": 0, "chunks": 0, "errors": []}

    for n in range(start_chapter, end_chapter + 1):
        # 查找章节文件
        matches = list(chapters_dir.glob(f"第{n:03d}章*.md"))
        if not matches:
            matches = list(chapters_dir.glob(f"第{n}章*.md"))
        if not matches:
            stats["errors"].append(f"章节 {n}: 文件未找到")
            continue

        chapter_file = matches[0]
        try:
            text = chapter_file.read_text(encoding="utf-8")
            # 去掉开头的 markdown 元信息（标题等）
            lines = text.split("\n")
            if lines and lines[0].startswith("#"):
                text = "\n".join(lines[1:]).strip()

            added = index_chapter(n, text)
            stats["chapters"] += 1
            stats["chunks"] += added
            logger.info(f"章节 {n} 建索引完成: {added} 块")
        except Exception as e:
            stats["errors"].append(f"章节 {n}: {e}")
            logger.error(f"章节 {n} 建索引失败: {e}")

    return stats


# ── 召回结果格式化 ───────────────────────────────────────────────────────────
def format_search_results(results: list[dict], max_text_len: int = 300) -> str:
    """将搜索结果格式化为可读字符串，用于注入 writer prompt。"""
    if not results:
        return "（未找到相关历史片段）"

    lines = []
    for i, r in enumerate(results, 1):
        text = r["text"]
        if len(text) > max_text_len:
            text = text[:max_text_len] + "……"
        chapter = r["chapter_num"]
        score = r["score"]
        tags = "/".join(r["tags"]) if r["tags"] else "无标签"
        lines.append(
            f"【相关片段{i}】（第{chapter}章 | 相关度:{score} | {tags}）\n{text}"
        )
    return "\n\n".join(lines)


if __name__ == "__main__":
    # 一次性建索引脚本
    import sys
    from pathlib import Path

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

    chapters_dir = Path(__file__).parent.parent / "正文章节"
    end = int(sys.argv[1]) if len(sys.argv) > 1 else 29

    print(f"开始为 1~{end} 章建索引...")
    stats = build_index_from_chapters(chapters_dir, 1, end)
    print(f"\n完成：{stats['chapters']} 章，{stats['chunks']} 块")
    if stats["errors"]:
        print(f"错误：{stats['errors']}")
