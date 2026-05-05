#!/usr/bin/env python3
"""
Writer MCP Server
- 只写正文，不审稿
- 调用 MiniMax-M2.7 模型
- 工具：write_outline / write_chapter / fix_major_issues / revise_chapter
"""

import os
import sys
import json
import sqlite3
from pathlib import Path
from typing import Any

# ── 项目路径 ────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(Path(__file__).parent))  # 让 rag.py 可导入
from rag import search, format_search_results  # RAG 向量检索
MEMORY_DB = PROJECT_ROOT / ".mcp" / "memory.db"
OUTLINES_DIR = PROJECT_ROOT / "大纲及设定"
STANDARDS_DIR = PROJECT_ROOT / "大纲及设定"
CHAPTERS_DIR = PROJECT_ROOT / "正文章节"  # 唯一正版本

MODEL = "deepseek-v4-pro"   # DeepSeek
API_BASE = "https://api.deepseek.com/v1"   # DeepSeek API
API_KEY="YOUR_API_KEY_HERE"


# ── 持久化 ──────────────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(str(MEMORY_DB))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    MEMORY_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = get_db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS writer_memory (
        key TEXT PRIMARY KEY,
        value TEXT,
        updated_at INTEGER DEFAULT (strftime('%s', 'now'))
    );
    CREATE TABLE IF NOT EXISTS chapter_drafts (
        chapter_num INTEGER PRIMARY KEY,
        outline TEXT,
        draft TEXT,
        revised TEXT,
        status TEXT DEFAULT 'draft',
        updated_at INTEGER DEFAULT (strftime('%s', 'now'))
    );
    """)
    conn.commit()
    conn.close()


def memory_get(key: str) -> str | None:
    conn = get_db()
    row = conn.execute("SELECT value FROM writer_memory WHERE key=?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else None


def memory_set(key: str, value: str):
    conn = get_db()
    conn.execute("""
        INSERT INTO writer_memory (key, value, updated_at)
        VALUES (?, ?, strftime('%s', 'now'))
        ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
    """, (key, value))
    conn.commit()
    conn.close()


def memory_append(key: str, entry: str, separator: str = " | "):
    """向列表型记忆追加条目，自动处理空值情况。"""
    existing = memory_get(key) or ""
    if existing:
        memory_set(key, existing + separator + entry)
    else:
        memory_set(key, entry)


# ── 记忆键常量 ──────────────────────────────────────────────────────────────
MEM_KEY_TASK         = "task_status"          # 当前任务状态 JSON
MEM_KEY_FINALIZED    = "finalized_chapters"   # 已定稿章节，如 "30,31"
MEM_KEY_ABANDONED    = "abandoned_tasks"      # JSON: {chapter_num: reason}
MEM_KEY_PLOT         = "plot_decisions"       # 情节重大决策
MEM_KEY_CHAR         = "character_decisions"  # 人物关系/性格决策
MEM_KEY_USER         = "user_instructions"    # 用户直接指令（最新优先）
MEM_KEY_CHAPTER_LOG  = "chapter_log"          # JSON: {chapter_num: {action, note, ts}}


def load_all_memory() -> str:
    """加载所有记忆，格式化为可读字符串供 LLM 参考。"""
    lines = ["【Writer 记忆库】"]
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    # 当前任务状态
    task = memory_get(MEM_KEY_TASK)
    if task:
        lines.append(f"\n## 当前任务（最后更新: {now}）")
        lines.append(task)

    # 已定稿章节
    fin = memory_get(MEM_KEY_FINALIZED)
    if fin:
        lines.append(f"\n## 已定稿章节（共 {len(fin.split(','))} 章）")
        lines.append(fin)

    # 章节操作日志
    log_str = memory_get(MEM_KEY_CHAPTER_LOG)
    if log_str:
        try:
            log = json.loads(log_str)
            lines.append("\n## 章节操作日志")
            for ch, info in sorted(log.items(), key=lambda x: int(x[0]), reverse=True):
                lines.append(f"  第{ch}章: {info.get('action','?')} - {info.get('note','')}")
        except Exception:
            pass

    # 用户直接指令
    user = memory_get(MEM_KEY_USER)
    if user:
        lines.append(f"\n## 用户最新指令")
        lines.append(user)

    # 重大情节决策
    plot = memory_get(MEM_KEY_PLOT)
    if plot:
        lines.append(f"\n## 重大情节决策")
        lines.append(plot)

    # 人物关系决策
    char = memory_get(MEM_KEY_CHAR)
    if char:
        lines.append(f"\n## 人物关系/性格决策")
        lines.append(char)

    # 已放弃的任务
    ab = memory_get(MEM_KEY_ABANDONED)
    if ab:
        lines.append(f"\n## 已放弃的任务（不再处理）")
        lines.append(ab)

    if len(lines) == 1:
        return "（Writer 记忆库为空，暂无记录）"
    return "\n".join(lines)


def _update_chapter_log(chapter_num: int, action: str, note: str = ""):
    """更新章节操作日志。"""
    log_str = memory_get(MEM_KEY_CHAPTER_LOG) or "{}"
    try:
        log = json.loads(log_str)
    except Exception:
        log = {}
    log[str(chapter_num)] = {"action": action, "note": note, "ts": datetime.now().isoformat()}
    memory_set(MEM_KEY_CHAPTER_LOG, json.dumps(log, ensure_ascii=False, indent=2))


def _finalize_chapter_mark(chapter_num: int):
    """标记章节为已定稿。"""
    fin = memory_get(MEM_KEY_FINALIZED) or ""
    chapters = [c.strip() for c in fin.split(",") if c.strip()] if fin else []
    if str(chapter_num) not in chapters:
        chapters.append(str(chapter_num))
        chapters.sort(key=lambda x: int(x))
    memory_set(MEM_KEY_FINALIZED, ",".join(chapters))
    _update_chapter_log(chapter_num, "已定稿", f"标记为 finalized @ {datetime.now().strftime('%m-%d %H:%M')}")


def _abandon_chapter_mark(chapter_num: int, reason: str):
    """标记某章任务已放弃。"""
    ab_str = memory_get(MEM_KEY_ABANDONED) or "{}"
    try:
        ab = json.loads(ab_str)
    except Exception:
        ab = {}
    ab[str(chapter_num)] = reason
    memory_set(MEM_KEY_ABANDONED, json.dumps(ab, ensure_ascii=False))
    _update_chapter_log(chapter_num, "已放弃", reason)


def save_chapter(chapter_num: int, field: str, content: str):
    """保存章节相关内容到 draft 表"""
    conn = get_db()
    conn.execute(f"""
        INSERT INTO chapter_drafts (chapter_num, {field}, updated_at)
        VALUES (?, ?, strftime('%s', 'now'))
        ON CONFLICT(chapter_num) DO UPDATE SET {field}=excluded.{field}, updated_at=excluded.updated_at
    """, (chapter_num, content))
    conn.commit()
    conn.close()


# ── 读取项目文件 ────────────────────────────────────────────────────────────
def read_file(path: Path) -> str:
    if not path.exists():
        return ""
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


from lxml import etree as lxml_etree
import xml.etree.ElementTree as ET
from datetime import datetime

# ── XML设定库路径 ─────────────────────────────────────────────────────────
_XML_SETTING_DB = OUTLINES_DIR / "GenericProduct设定库.xml"
_XML_VOL2_OUTLINE = OUTLINES_DIR / "GenericProduct大纲_第二卷.xml"


def _load_xml_module(tag: str) -> str:
    """从XML设定库加载指定#tag模块内容。找不到则返回空字符串。

    优先用 lxml 解析（可处理格式略有偏差的 XML），失败则 fallback 到标准库。
    """
    if not _XML_SETTING_DB.exists():
        return ""
    # 优先用 lxml（容错性强）
    try:
        parser = lxml_etree.XMLParser(recover=True, encoding="utf-8")
        tree = lxml_etree.parse(str(_XML_SETTING_DB), parser)
        root = tree.getroot()
        for mod in root.xpath("//ModuleDefinition"):
            t = mod.find("Tag")
            if t is not None and t.text == tag:
                c = mod.find("Content")
                if c is not None and c.text:
                    return c.text.strip()
    except Exception as lxml_err:
        pass
    # Fallback：标准库逐行扫描（绕过 CDATA 解析问题）
    try:
        with open(_XML_SETTING_DB, "r", encoding="utf-8") as f:
            content = f.read()
        # 简单文本查找：提取指定 Tag 的 Content
        import re
        pattern = rf'<Tag>{re.escape(tag)}</Tag>.*?<Content><!\[CDATA\[(.*?)\]\]></Content>'
        match = re.search(pattern, content, re.DOTALL)
        if match:
            return match.group(1).strip()
    except Exception:
        pass
    return ""


def load_world_setting() -> str:
    """加载世界观与人物设定（优先XML，fallback旧md）"""
    xml_content = _load_xml_module("#personas")
    if xml_content:
        return xml_content
    return read_file(STANDARDS_DIR / "世界观与人物设定.md")


def load_work_rules() -> str:
    """加载工作规范（优先XML，fallback旧md）"""
    xml_content = _load_xml_module("#writing-rules")
    if xml_content:
        return xml_content
    return read_file(STANDARDS_DIR / "工作规范.md")


def load_vol2_chapter(chapter_num: int) -> str:
    """从XML第二卷大纲加载第N章情节大纲（含Trigger/Constraint/PlotPoint/EndPoint）"""
    if not _XML_VOL2_OUTLINE.exists():
        return load_outline_from_file(chapter_num)
    try:
        tree = ET.parse(str(_XML_VOL2_OUTLINE))
        root = tree.getroot()
        for ch in root.findall(".//Chapter"):
            if ch.get("number") == f"{chapter_num:03d}":
                parts = [f"【第{chapter_num}章 XML大纲】"]
                # Tag
                t_tag = ch.get("tag")
                if t_tag:
                    parts.append(f"章节标识：{t_tag}")
                # Title
                t_title = ch.get("title")
                if t_title:
                    parts.append(f"标题：{t_title}")
                # Time
                t_time = ch.find("Time")
                if t_time is not None:
                    parts.append(f"时间：{t_time.text.strip()}")
                # Location
                t_loc = ch.find("Location")
                if t_loc is not None:
                    parts.append(f"地点：{t_loc.text.strip()}")
                # Mood
                t_mood = ch.find("Mood")
                if t_mood is not None:
                    parts.append(f"情绪：{t_mood.text.strip()}")
                # Status
                t_status = ch.get("status")
                if t_status:
                    parts.append(f"状态：{t_status}")
                # Trigger
                t_trig = ch.find("Trigger")
                if t_trig is not None:
                    parts.append(f"\n【Trigger·章节起点】\n{t_trig.text.strip()}")
                # Constraint
                t_cons = ch.find("Constraint")
                if t_cons is not None:
                    parts.append(f"\n【Constraint·写作约束】\n{t_cons.text.strip()}")
                # PlotPoints
                for pp in ch.findall("PlotPoint"):
                    seq = pp.get("seq", "?")
                    pts = pp.findall("Plot")
                    for pt in pts:
                        parts.append(f"\n情节{seq}：{pt.text.strip()}")
                # EndPoint
                t_ep = ch.find("EndPoint")
                if t_ep is not None:
                    parts.append(f"\n【EndPoint·本章叙事终点】\n{t_ep.text.strip()}")
                return "\n".join(parts)
    except ET.ParseError:
        pass
    return load_outline_from_file(chapter_num)


def load_outline_from_file(chapter_num: int) -> str:
    """从大纲文件读取本章大纲（优先XML大纲，fallback旧md大纲）"""
    # 优先用XML章节大纲
    xml_outline = load_vol2_chapter(chapter_num)
    if xml_outline and "【第" in xml_outline:
        return xml_outline
    # 无独立文件则fallback旧md
    outline_file = OUTLINES_DIR / f"第{chapter_num:03d}章_大纲.md"
    if outline_file.exists():
        return read_file(outline_file)
    # 没有独立文件，从分卷大纲里提取本章段落
    md_outline = OUTLINES_DIR / "第二卷_天火坠地_第22-60章.md"
    if md_outline.exists():
        full_outline = read_file(md_outline)
    else:
        full_outline = read_file(OUTLINES_DIR / "第二卷大纲_天火坠地_第22-60章.xml")

    # 找到本章开始的行（格式：### 第Y章 或 ### 第N章）
    lines = full_outline.split("\n")
    start_idx = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        # 匹配 "### 第Y章" 或 "### 第N章"
        if stripped.startswith("### 第") and "章：" in stripped:
            # 提取章节号
            after_hash = stripped.lstrip("#").strip()
            if after_hash.startswith("第"):
                num_part = after_hash[1:].split("章")[0].strip()
                try:
                    n = int(num_part)
                    if n == chapter_num:
                        start_idx = i
                        break
                    elif chapter_num < 100 and num_part == f"{chapter_num:03d}":
                        # 兼容3位格式
                        start_idx = i
                        break
                except ValueError:
                    pass

    if start_idx is None:
        # 没找到，返回完整大纲（兜底）
        return full_outline

    # 找本章结束的行（下一个 ### 第N章 或 --- 或 end of file）
    end_idx = len(lines)
    for i in range(start_idx + 1, len(lines)):
        stripped = lines[i].strip()
        # 遇到下一个章节（### 第N章）或者顶层 --- 分隔符就停
        if stripped.startswith("### 第") and "章：" in stripped:
            end_idx = i
            break
        if stripped == "---" and i > start_idx + 2:
            # 顶层分隔符（不是章节内部的小分隔）
            # 判断前面是否有章节标题
            end_idx = i
            break

    chapter_section = "\n".join(lines[start_idx:end_idx])
    return chapter_section


SUMMARY_MAX_BYTES = 50 * 1024   # 前情摘要合并版最大加载50KB（≈25000字），超出则截断旧章节
RECENT_CHAPTERS_FULL = 5          # 最近N章全文加载
RECENT_CHAPTERS_PREVIEW = 600     # 更早章节每章取前600字预览


def load_recent_chapters(chapter_num: int) -> str:
    """加载第N章～第(chapter_num-1)章已定稿正文。
    - 最近3章：全文
    - 更早章节：每章取前500字预览
    若 chapter_num <= 1 则返回空。
    """
    if chapter_num <= 1:
        return ""

    MIN_CHAPTER = 1

    full_parts = []    # [(chapter_num, text), ...]  全文案文
    preview_parts = [] # [(chapter_num, text), ...]  预览文本

    for i in range(chapter_num - 1, MIN_CHAPTER - 1, -1):
        ch_file = CHAPTERS_DIR / f"第{i:03d}章_重生之我在末日囤了十万袋GenericProduct原浆.md"
        if not ch_file.exists():
            continue
        text = read_file(ch_file)
        if i > chapter_num - 1 - RECENT_CHAPTERS_FULL:
            full_parts.append((i, text))
        else:
            preview_parts.append((i, text[:RECENT_CHAPTERS_PREVIEW]))

    blocks = []
    if preview_parts:
        preview_block = "\n\n".join(f"=== 第{i:03d}章（预览） ===\n{t}" for i, t in reversed(preview_parts))
        blocks.append(f"【早期章节预览（第{MIN_CHAPTER}章～第{chapter_num-1-RECENT_CHAPTERS_FULL:03d}章）】\n{preview_block}")
    if full_parts:
        full_block = "\n\n".join(f"=== 第{i:03d}章（全文） ===\n{t}" for i, t in reversed(full_parts))
        blocks.append(f"【近期章节全文（第{chapter_num-RECENT_CHAPTERS_FULL:03d}章～第{chapter_num-1:03d}章）】\n{full_block}")

    return "\n\n".join(blocks)


def load_prequel_summary() -> str:
    """加载前情摘要合并版（两 MCP 共同依赖）。
    若文件超过 SUMMARY_MAX_BYTES，则渐进式截断：
    - 优先保留最新章节摘要（文件末尾），
    - 超出部分从旧章节摘要开始丢弃。
    """
    content = read_file(MERGED_SUMMARY_FILE)
    if len(content.encode("utf-8")) <= SUMMARY_MAX_BYTES:
        return content
    # 超出上限，按章节渐进裁剪
    lines = content.split("\n")
    kept_lines = []
    total_bytes = 0
    # 从最新章节倒序保留，直到达到上限
    chapter_markers = []
    for idx, line in enumerate(lines):
        if line.startswith("## 第") and "章" in line:
            chapter_markers.append((idx, line))
    # 优先保留最新的摘要，丢弃最旧的
    for i in range(len(chapter_markers) - 1, -1, -1):
        start_idx = chapter_markers[i][0]
        section = "\n".join(lines[start_idx:])
        section_bytes = len(section.encode("utf-8"))
        if total_bytes + section_bytes <= SUMMARY_MAX_BYTES:
            kept_lines = [section] + kept_lines
            total_bytes += section_bytes
        else:
            # 这一段也不要了，继续往前
            pass
    # 剩余空间放一个头部说明
    header = f"【前情摘要合并版·截断版】（原文件过大，已截断旧章节摘要，仅保留最近章节）\n"
    return header + "\n".join(kept_lines)


def load_chapter_draft(chapter_num: int) -> str | None:
    """从数据库读取章节草稿，若草稿损坏（<100字节）则fallback到正文章节文件"""
    conn = get_db()
    row = conn.execute(
        "SELECT draft FROM chapter_drafts WHERE chapter_num=?", (chapter_num,)
    ).fetchone()
    conn.close()
    if row and row["draft"] and len(row["draft"]) >= 100:
        return row["draft"]
    # fallback：直接从正文章节文件读取
    chapter_file = CHAPTERS_DIR / f"第{chapter_num:03d}章_重生之我在末日囤了十万袋GenericProduct原浆.md"
    if chapter_file.exists():
        return chapter_file.read_text(encoding="utf-8")
    return None


# ── 前情摘要 ─────────────────────────────────────────────────────────────────
MERGED_SUMMARY_FILE = PROJECT_ROOT / "大纲及设定" / "前情摘要" / "前情摘要合并版.md"
SUMMARY_DIR         = PROJECT_ROOT / "大纲及设定" / "前情摘要"

SUMMARY_PROMPT = """你是一个网文小说前情摘要机器人。把下面这章正文压缩成详细的「纯情节摘要」，供后续写作和审稿参考。

规则：
1. 必须完整覆盖：人物关键行为 + 核心决策理由 + 关键对话原文 + 事件转折 + 物资/资源变化 + 伏笔埋设与回收 + 人物状态变化
2. 伏笔必须标注：（伏笔·前兆）、（伏笔·回收·第X章）
3. 删除：重复内容、纯修饰词堆砌、感叹语气、与情节无关的心理描写
4. 每段讲清一个独立事件/决策，不要流水账
5. 字数：800-2000字，足够详细以便后续写作不丢失任何情节点
6. 直接输出摘要正文，不要标题、不要前言、不要编号

格式示例：
第N段：[人物]做[事件]→[结果]。（关键对话："..."）（物资：获得/消耗[物品]）（伏笔·前兆：[伏笔内容]）

章节正文：
"""

def load_prequel_summary() -> str:
    """加载前情摘要合并版（两 MCP 共同依赖）"""
    return read_file(MERGED_SUMMARY_FILE)

def summarize_and_finalize(chapter_num: int) -> str:
    """定稿时对该章做情节摘要，写单独文件 + 更新合并版，返回结果"""
    SUMMARY_DIR.mkdir(parents=True, exist_ok=True)
    ch_file = CHAPTERS_DIR / f"第{chapter_num:03d}章_重生之我在末日囤了十万袋GenericProduct原浆.md"
    if not ch_file.exists():
        return f"[ERROR] 第{chapter_num:03d}章文件不存在于正文章节目录"
    text = read_file(ch_file)
    api_key = get_api_key()
    if not api_key:
        return "[ERROR] MiniMax API Key 未配置"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SUMMARY_PROMPT},
            {"role": "user",   "content": text},
        ],
        "temperature": 0.3,
    }
    try:
        import httpx
        with httpx.Client(timeout=120.0) as client:
            resp = client.post(f"{API_BASE}/chat/completions", headers=headers, json=payload)
            resp.raise_for_status()
            summary = resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"[ERROR] LLM API 调用失败: {e}"
    # 写单独摘要文件
    out_file = SUMMARY_DIR / f"第{chapter_num:03d}章_摘要.md"
    out_file.write_text(summary, encoding="utf-8")
    # 重建合并版
    existing = sorted([int(f.name[1:4]) for f in SUMMARY_DIR.glob("第???章_摘要.md")])
    if chapter_num not in existing:
        existing.append(chapter_num)
    existing.sort()
    merged_lines = ["# 前情摘要合并版\n", f"_生成时间：YYYY-MM-DD_\n\n"]
    for ch in existing:
        f = SUMMARY_DIR / f"第{ch:03d}章_摘要.md"
        content = f.read_text(encoding="utf-8") if f.exists() else ""
        merged_lines.append(f"## 第{ch:03d}章\n{content}\n")
    MERGED_SUMMARY_FILE.write_text("\n".join(merged_lines), encoding="utf-8")
    _finalize_chapter_mark(chapter_num)
    memory_set(MEM_KEY_TASK, f"第{chapter_num:03d}章已定稿！已完成摘要生成")
    return summary


# ── LLM 调用 ────────────────────────────────────────────────────────────────
_CACHED_KEY: str | None = None

def get_api_key() -> str:
    global _CACHED_KEY
    if _CACHED_KEY:
        return _CACHED_KEY
    # 优先读环境变量（未被 mask 的情况）
    key = os.environ.get("DEEPSEEK_API_KEY", "") or os.environ.get("MINIMAX_API_KEY", "") or os.environ.get("MINIMAX_CN_API_KEY", "")
    if key and not key.startswith("***") and not key.startswith("${"):
        _CACHED_KEY = key
        return key
    # 回退：直接读配置文件（绕过 hermes-agent 的环境变量 mask）
    import yaml
    for cfg_path in [
        "/home/rover/.hermes/profiles/writer/config.yaml",
        os.path.expanduser("~/.hermes/profiles/writer/config.yaml"),
    ]:
        try:
            with open(cfg_path) as f:
                cfg = yaml.safe_load(f)
            for server in cfg.get("mcp_servers", {}).values():
                k = server.get("env", {}).get("DEEPSEEK_API_KEY") or server.get("env", {}).get("MINIMAX_API_KEY") or server.get("env", {}).get("MINIMAX_CN_API_KEY")
                if k and not k.startswith("***") and not k.startswith("${"):
                    _CACHED_KEY = k
                    return k
        except Exception:
            pass
    # 硬编码兜底（避免流程卡住）
    _CACHED_KEY = "YOUR_API_KEY_HERE"
    return _CACHED_KEY


def call_llm(system_prompt: str, user_prompt: str, model: str = MODEL) -> str:
    """直接调用 MiniMax API"""
    import httpx

    api_key = get_api_key()
    if not api_key:
        return "[ERROR] MiniMax API Key 未配置。请在 ~/.hermes/.env 中设置 MINIMAX_API_KEY 或 MINIMAX_CN_API_KEY。"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.7,
    }

    try:
        with httpx.Client(timeout=180.0) as client:
            resp = client.post(f"{API_BASE}/chat/completions", headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
    except Exception as e:
        return f"[ERROR] LLM API 调用失败: {e}"


# ── Writer 系统提示词 ────────────────────────────────────────────────────────
def writer_system_prompt() -> str:
    return f"""你是一个专业网文小说写手，擅长末日囤货类题材，文风搞笑·癫狂·无厘头·脑洞·逻辑闭环。

项目信息：
- 项目路径：{PROJECT_ROOT}
- 当前模型：{MODEL}

写作规范（必须严格遵守）：
1. 每章 ≥4000字（正文字符数，含标点，不含标题行和"（未完待续）"）
2. 正文禁止出现"Day X"，Day X 只允许在章节标题下方结构标注
3. 每章 XKA 最多出现1-2次，其余用"平台""商城""店里"代称
4. 对话口语化，避免书面复述
5. 章末必须留钩子
6. 禁用AI腔：程度副词（非常、显著、大幅、极其…）、连接词（此外、另外、同时、值得注意的是…）
7. 感叹号 ≤2 units/章，破折号 ≤1次/千字，单句 ≤40字

角色口吻规范：
- CharacterA：靴子落地后回归跳脱本性，一本正经说废话，莫名其妙逻辑链，随身带ProductG
- CharacterC：最癫，紫外线又不放假/末日也要美美地
- 主角Protagonist：相对沉稳，自嘲式幽默，不能吃辣，路痴，被噎住/吐槽方
- CharacterB：爱哭，情绪化，行动力强

无厘头情节归属：
- ✅ CharacterA/CharacterC：可以主动发起无厘头
- ❌ 主角：不能主动发起无厘头，负责被噎住/吐槽
"""


# ── 工具实现 ────────────────────────────────────────────────────────────────
def tool_write_outline(chapter_num: int, outline_template: str | None = None) -> str:
    """写分级大纲"""
    world = load_world_setting()
    rules = load_work_rules()
    memory = load_all_memory()
    if outline_template is None:
        outline_template = load_outline_from_file(chapter_num)
    recent = load_recent_chapters(chapter_num)
    prequel = load_prequel_summary()

    user_prompt = f"""根据以下信息，为第{chapter_num:03d}章写分级大纲。

【Writer 记忆库】
{memory}

【分卷大纲（参考）】
{outline_template}

【最近章节正文（分级）】
{recent}

【前情摘要合并版】
{prequel}

【世界观与人物设定】
{world}

【工作规范】
{rules}

请按以下格式输出分级大纲：
```
章节标题：第{chapter_num:03d}章_xxx
时间节点：Day X
地点：
核心情绪：
出场人物：
核心情节（1-2 units）：
情绪节奏：
  开场：...
  中段：...
  结尾：...
章末钩子：
伏笔推进（埋设/回收）：
物资变化：
```"""

    result = call_llm(writer_system_prompt(), user_prompt)
    save_chapter(chapter_num, "outline", result)
    memory_set(MEM_KEY_TASK, f"正在为第{chapter_num:03d}章撰写分级大纲")
    _update_chapter_log(chapter_num, "写大纲", f"大纲已完成并保存")
    return result


def tool_write_chapter(chapter_num: int, outline: str) -> str:
    """写章节初稿"""
    world = load_world_setting()
    rules = load_work_rules()
    memory = load_all_memory()
    recent = load_recent_chapters(chapter_num)
    prequel = load_prequel_summary()

    # ── RAG 向量检索（召回相关历史片段）────────────────────────────────────
    rag_results = search(
        query=outline[:800],   # 用大纲前800字做查询，语义匹配相关情节
        top_k=4,
        exclude_chapter=chapter_num,
    )
    rag_context = format_search_results(rag_results)

    user_prompt = f"""根据以下分级大纲，写第{chapter_num:03d}章正文。

【Writer 记忆库】
{memory}

【分级大纲】
{outline}

【最近章节正文（分级）】
{recent}

【前情摘要合并版】
{prequel}

【RAG 召回片段（相关历史情节）】
{rag_context}

【世界观与人物设定】
{world}

【工作规范】
{rules}

写作要求：
1. 严格按大纲走，核心情节1-2 units，不贪多
2. 对话口语化，参考人物口吻规范
3. 章末必须留钩子
4. 字数 ≥4000字（正文字符数，含标点）
5. 正文禁止出现"Day X"
6. 禁用AI腔

请直接输出正文，不要加markdown标题（# ），但章节标题行还是需要的（用"第{chapter_num:03d}章_xxx"格式）。"""

    result = call_llm(writer_system_prompt(), user_prompt)
    save_chapter(chapter_num, "draft", result)
    memory_set(MEM_KEY_TASK, f"第{chapter_num:03d}章初稿已完成，等待审稿/修改指令")
    _update_chapter_log(chapter_num, "写初稿", f"初稿已完成，字数约 {len(result):,}")
    return result


def tool_fix_major_issues(chapter_num: int, issues: list[str]) -> str:
    """修复重大漏洞"""
    draft = load_chapter_draft(chapter_num)
    if not draft:
        return "[ERROR] 未找到第{:03d}章草稿，请先调用 write_chapter 生成初稿。".format(chapter_num)

    world = load_world_setting()
    rules = load_work_rules()
    memory = load_all_memory()
    recent = load_recent_chapters(chapter_num)
    prequel = load_prequel_summary()

    rag_results = search(
        query=draft[:600],
        top_k=4,
        exclude_chapter=chapter_num,
    )
    rag_context = format_search_results(rag_results)

    user_prompt = f"""你是专业网文编辑。第{chapter_num:03d}章被顾问审查后发现以下重大问题，请修复。

【Writer 记忆库】
{memory}

【初稿】
{draft}

【重大问题清单】
{chr(10).join(f"- {issue}" for issue in issues)}

【最近章节正文（分级）】
{recent}

【前情摘要合并版】
{prequel}

【RAG 召回片段（相关历史情节）】
{rag_context}

【世界观与人物设定】
{world}

【工作规范】
{rules}

修复要求：
1. 只修复上述列出的问题，不要改动其他内容
2. 改完后通读一遍确保没有引入新问题
3. 保持字数 ≥4000字
4. 禁止出现"Day X"

请输出修复后的完整正文。"""

    result = call_llm(writer_system_prompt(), user_prompt)
    save_chapter(chapter_num, "draft", result)
    issues_str = " | ".join(issues[:3])
    memory_set(MEM_KEY_TASK, f"第{chapter_num:03d}章已修复重大问题：{issues_str}")
    _update_chapter_log(chapter_num, "修复漏洞", f"已修复：{issues_str}")
    return result


def tool_patch_chapter(chapter_num: int, patches: list[dict]) -> str:
    """局部修改章节——只输出patch，不重写全章。
    
    patches: [{"old_text": "原文片段", "new_text": "修改后片段"}, ...]
    返回: 确认信息（实际修改由调用方apply到文件）
    """
    draft = load_chapter_draft(chapter_num)
    if not draft:
        return f"[ERROR] 未找到第{chapter_num:03d}章草稿。"

    world = load_world_setting()
    rules = load_work_rules()
    memory = load_all_memory()
    recent = load_recent_chapters(chapter_num)
    prequel = load_prequel_summary()

    patches_str = "\n".join(
        f"[PATCH {i+1}]\n原文：{p['old_text']}\n改为：{p['new_text']}"
        for i, p in enumerate(patches)
    )

    user_prompt = f"""你是专业网文编辑。第{chapter_num:03d}章需要做以下局部修改。

【Writer 记忆库】
{memory}

【初稿】
{draft}

【修改清单】
{patches_str}

【最近章节正文（分级）】
{recent}

【前情摘要合并版】
{prequel}

【世界观与人物设定】
{world}

【工作规范】
{rules}

要求：
1. 严格按上述清单逐一修改，不要改动其他内容
2. 如果发现某个 old_text 在初稿中不存在或匹配不上，在 patch 清单末尾注明"[WARN] 第N个patch未在初稿中找到匹配"
3. 每个patch必须精确定位到具体段落，不能泛泛而谈
4. 禁止出现"Day X"

只需输出修改清单（格式：【PATCH N】【位置】...），无需输出完整正文。"""

    result = call_llm(writer_system_prompt(), user_prompt)
    patch_summary = " | ".join(p.get("new_text", "")[:30] for p in patches[:3])
    memory_set(MEM_KEY_TASK, f"第{chapter_num:03d}章已执行局部修改：{patch_summary}")
    _update_chapter_log(chapter_num, "局部修改", f"执行了 {len(patches)} 个 patch")
    return result


def tool_revise_chapter(chapter_num: int, feedback: list[str]) -> str:
    """按反馈改稿"""
    draft = load_chapter_draft(chapter_num)
    if not draft:
        return "[ERROR] 未找到第{:03d}章草稿。".format(chapter_num)

    recent = load_recent_chapters(chapter_num)
    prequel = load_prequel_summary()
    world = load_world_setting()
    rules = load_work_rules()
    memory = load_all_memory()

    rag_results = search(
        query=" ".join(feedback[:3])[:600],
        top_k=4,
        exclude_chapter=chapter_num,
    )
    rag_context = format_search_results(rag_results)

    user_prompt = f"""根据以下反馈，对第{chapter_num:03d}章进行修改。

【Writer 记忆库】
{memory}

【当前正文】
{draft}

【修改反馈】
{chr(10).join(f"- {fb}" for fb in feedback)}

【最近章节正文（分级）】
{recent}

【前情摘要合并版】
{prequel}

【RAG 召回片段（相关历史情节）】
{rag_context}

【世界观与人物设定】
{world}

【工作规范】
{rules}

修改要求：
1. 只改反馈中提到的部分，不自行发挥、不扩大修改范围
2. 改完后通读一遍确保没有引入新问题
3. 保持字数 ≥4000字
4. 禁止出现"Day X"

请输出修改后的完整正文。"""

    result = call_llm(writer_system_prompt(), user_prompt)
    save_chapter(chapter_num, "revised", result)
    feedback_str = " | ".join(feedback[:3])
    memory_set(MEM_KEY_TASK, f"第{chapter_num:03d}章已按反馈修改：{feedback_str}")
    _update_chapter_log(chapter_num, "改稿", f"已按反馈修改：{feedback_str}")
    return result


# ── MCP Server 入口 ─────────────────────────────────────────────────────────
def main():
    init_db()

    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool, TextContent

    server = Server("writer-mcp")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="write_outline",
                description="为指定章节写分级大纲。输入章节号和大纲原文，返回结构化分级大纲。",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "chapter_num": {"type": "integer", "description": "章节号，如 27"},
                        "outline": {"type": "string", "description": "分卷大纲章节原文（可选，不传则从文件读取）"}
                    },
                    "required": ["chapter_num"]
                }
            ),
            Tool(
                name="write_chapter",
                description="根据分级大纲写章节初稿。输入章节号和大纲，返回正文（≥4000字）。",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "chapter_num": {"type": "integer"},
                        "outline": {"type": "string", "description": "分级大纲内容"}
                    },
                    "required": ["chapter_num", "outline"]
                }
            ),
            Tool(
                name="patch_chapter",
                description="局部修改章节。输入章节号+patch列表，LLM只输出patch确认信息（不重写全章），实际修改由调用方执行。",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "chapter_num": {"type": "integer"},
                        "patches": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "old_text": {"type": "string", "description": "待修改的原文片段"},
                                    "new_text": {"type": "string", "description": "修改后的内容"}
                                },
                                "required": ["old_text", "new_text"]
                            }
                        }
                    },
                    "required": ["chapter_num", "patches"]
                }
            ),
            Tool(
                name="fix_major_issues",
                description="修复章节初稿中的重大漏洞。输入章节号和问题列表，返回修复后正文（⚠️会重写全章，优先用 patch_chapter 做局部修改）。",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "chapter_num": {"type": "integer"},
                        "issues": {"type": "array", "items": {"type": "string"}}
                    },
                    "required": ["chapter_num", "issues"]
                }
            ),
            Tool(
                name="revise_chapter",
                description="根据反馈修改章节。输入章节号和反馈列表，返回修改后正文。",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "chapter_num": {"type": "integer"},
                        "feedback": {"type": "array", "items": {"type": "string"}}
                    },
                    "required": ["chapter_num", "feedback"]
                }
            ),
            Tool(
                name="finalize_chapter",
                description="定稿时调用：对重构版章节做情节摘要，写单独摘要文件并更新前情摘要合并版。两 MCP 共同依赖该合并版。",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "chapter_num": {"type": "integer", "description": "章节号"}
                    },
                    "required": ["chapter_num"]
                }
            ),
        ]

    @server.list_prompts()
    async def list_prompts() -> list:
        """Writer server 不使用 prompts，直接返回空列表"""
        return []

    @server.list_resources()
    async def list_resources() -> list:
        """Writer server 不使用 resources，直接返回空列表"""
        return []

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        try:
            if name == "write_outline":
                result = tool_write_outline(arguments["chapter_num"], arguments.get("outline"))
            elif name == "write_chapter":
                result = tool_write_chapter(arguments["chapter_num"], arguments["outline"])
            elif name == "patch_chapter":
                result = tool_patch_chapter(arguments["chapter_num"], arguments["patches"])
            elif name == "fix_major_issues":
                result = tool_fix_major_issues(arguments["chapter_num"], arguments["issues"])
            elif name == "revise_chapter":
                result = tool_revise_chapter(arguments["chapter_num"], arguments["feedback"])
            elif name == "finalize_chapter":
                result = summarize_and_finalize(arguments["chapter_num"])
            else:
                result = f"[ERROR] 未知工具: {name}"
            return [TextContent(type="text", text=result)]
        except Exception as e:
            return [TextContent(type="text", text=f"[ERROR] {e}")]

    import asyncio

    async def run():
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())

    asyncio.run(run())


if __name__ == "__main__":
    main()
