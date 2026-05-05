#!/usr/bin/env python3
"""
Consultant MCP Server
- 只审稿，不写正文
- 调用 MiniMax-M2.7 模型
- 重点：人设管理、情节连贯性、逻辑漏洞
- 工具：review_outline / review_chapter / review_feedback / check_plot_consistency
"""

import os
import json
import sqlite3
import re
from pathlib import Path
from typing import Any

# ── 项目路径 ────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
MEMORY_DB = PROJECT_ROOT / ".mcp" / "memory.db"
STANDARDS_DIR = PROJECT_ROOT / "大纲及设定"
CHAPTERS_DIR = PROJECT_ROOT / "正文章节"  # 唯一正版本

MODEL = "deepseek-v4-pro"   # DeepSeek
API_BASE = "https://api.deepseek.com/v1"   # DeepSeek API


# ── 持久化 ──────────────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(str(MEMORY_DB))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    MEMORY_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = get_db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS consultant_memory (
        key TEXT PRIMARY KEY,
        value TEXT,
        updated_at INTEGER DEFAULT (strftime('%s', 'now'))
    );
    CREATE TABLE IF NOT EXISTS review_records (
        chapter_num INTEGER,
        review_type TEXT,
        result TEXT,
        issues TEXT,
        reviewed_at INTEGER DEFAULT (strftime('%s', 'now')),
        PRIMARY KEY (chapter_num, review_type)
    );
    """)
    conn.commit()
    conn.close()


def memory_get(key: str) -> str | None:
    conn = get_db()
    row = conn.execute("SELECT value FROM consultant_memory WHERE key=?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else None


def memory_set(key: str, value: str):
    conn = get_db()
    conn.execute("""
        INSERT INTO consultant_memory (key, value, updated_at)
        VALUES (?, ?, strftime('%s', 'now'))
        ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
    """, (key, value))
    conn.commit()
    conn.close()


# ── 读取项目文件 ────────────────────────────────────────────────────────────
def read_file(path: Path) -> str:
    if not path.exists():
        return ""
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def load_outline_file(chapter_num: int) -> str:
    """加载本章独立大纲文件"""
    f = STANDARDS_DIR / f"第{chapter_num:03d}章_大纲.md"
    return read_file(f) if f.exists() else ""


def load_chapters_progress() -> str:
    return read_file(STANDARDS_DIR / "章节进度总表.md")


def load_foreshadow_table() -> str:
    return read_file(STANDARDS_DIR / "伏笔回收追踪表.md")


def load_work_rules() -> str:
    return read_file(STANDARDS_DIR / "工作规范.md")


def load_world_setting() -> str:
    return read_file(STANDARDS_DIR / "世界观与人物设定.md")


MERGED_SUMMARY_FILE = PROJECT_ROOT / "大纲及设定" / "前情摘要" / "前情摘要合并版.md"

def load_prequel_summary() -> str:
    """加载前情摘要合并版（两 MCP 共同依赖）。
    若文件超过 SUMMARY_MAX_BYTES，则渐进式截断：
    - 优先保留最新章节摘要（文件末尾），
    - 超出部分从旧章节摘要开始丢弃。
    """
    content = read_file(MERGED_SUMMARY_FILE)
    if len(content.encode("utf-8")) <= SUMMARY_MAX_BYTES:
        return content
    lines = content.split("\n")
    kept_lines = []
    total_bytes = 0
    chapter_markers = []
    for idx, line in enumerate(lines):
        if line.startswith("## 第") and "章" in line:
            chapter_markers.append((idx, line))
    for i in range(len(chapter_markers) - 1, -1, -1):
        start_idx = chapter_markers[i][0]
        section = "\n".join(lines[start_idx:])
        section_bytes = len(section.encode("utf-8"))
        if total_bytes + section_bytes <= SUMMARY_MAX_BYTES:
            kept_lines = [section] + kept_lines
            total_bytes += section_bytes
    header = f"【前情摘要合并版·截断版】（原文件过大，已截断旧章节摘要，仅保留最近章节）\n"
    return header + "\n".join(kept_lines)

SUMMARY_MAX_BYTES = 50 * 1024   # 前情摘要合并版最大加载50KB（≈25000字），超出则截断旧章节
RECENT_CHAPTERS_FULL = 5          # 最近N章全文加载
RECENT_CHAPTERS_PREVIEW = 600     # 更早章节每章取前600字预览


def load_recent_chapters(chapter_num: int) -> dict[int, str]:
    """加载第N章～第(chapter_num-1)章已定稿正文。
    - 最近5章：全文
    - 更早章节：每章取前600字预览
    """
    if chapter_num <= 1:
        return {}
    MIN_CH = 1
    result = {}
    for i in range(chapter_num - 1, MIN_CH - 1, -1):
        ch_file = CHAPTERS_DIR / f"第{i:03d}章_重生之我在末日囤了十万袋GenericProduct原浆.md"
        if not ch_file.exists():
            continue
        text = read_file(ch_file)
        if i > chapter_num - 1 - RECENT_CHAPTERS_FULL:
            result[i] = text  # 全文
        else:
            result[i] = text[:RECENT_CHAPTERS_PREVIEW]  # 预览
    return result


# ── LLM 调用 ────────────────────────────────────────────────────────────────
_CACHED_KEY: str | None = None

def get_api_key() -> str:
    global _CACHED_KEY
    if _CACHED_KEY:
        return _CACHED_KEY
    key = os.environ.get("DEEPSEEK_API_KEY", "") or os.environ.get("MINIMAX_API_KEY", "") or os.environ.get("MINIMAX_CN_API_KEY", "")
    if key and not key.startswith("***") and not key.startswith("${"):
        _CACHED_KEY = key
        return key
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
    _CACHED_KEY = "YOUR_API_KEY_HERE"
    return _CACHED_KEY


def _single_call(system_prompt: str, user_prompt: str, model: str = MODEL) -> str:
    import httpx

    api_key = get_api_key()
    if not api_key:
        return "[ERROR] MiniMax API Key 未配置。"

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
        "temperature": 0.3,  # 审查用低温，降低随机性
    }

    try:
        with httpx.Client(timeout=120.0) as client:
            resp = client.post(f"{API_BASE}/chat/completions", headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
    except Exception as e:
        return f"[ERROR] LLM API 调用失败: {e}"


def call_llm(system_prompt: str, user_prompt: str, model: str = MODEL, rounds: int = 1) -> str:
    """多轮思考版 LLM 调用。

    Args:
        system_prompt: 系统提示词
        user_prompt: 首轮用户 prompt
        model: 模型名
        rounds: 思考轮数（默认1，即退化为单次调用）
    """
    if rounds <= 1:
        return _single_call(system_prompt, user_prompt, model)

    ACCUM_MAX = 4000  # 轮次间传递的积累内容上限

    # 前 rounds-1 轮：逐步深化分析
    stages = ["问题定义", "深度分析", "综合结论"]
    accumulated = user_prompt
    for i in range(rounds - 1):
        stage = stages[min(i, len(stages) - 1)]
        round_prompt = (
            f"【{stage} 第 {i+1}/{rounds-1} 轮】\n"
            f"上一轮分析结论（已摘要）：\n{accumulated[:ACCUM_MAX]}\n\n"
            f"请在此基础上继续深入分析，给出更精准的判断。"
        )
        accumulated = _single_call(system_prompt, round_prompt, model)
        if accumulated.startswith("[ERROR]"):
            return accumulated  # 提前失败

    # 末轮：综合所有轮次，给出最终结论
    final_prompt = (
        f"【综合结论 第 {rounds}/{rounds} 轮】\n"
        f"经过 {rounds-1} 轮递进分析，结论如下：\n{accumulated[:ACCUM_MAX]}\n\n"
        f"请综合所有分析结论，给出最终审查结论。格式严格遵循系统提示词要求。"
    )
    return _single_call(system_prompt, final_prompt, model)


# ── Consultant 系统提示词 ─────────────────────────────────────────────────────
def consultant_system_prompt() -> str:
    return f"""你是一个专业网文小说顾问，擅长审查末日囤货类小说。

你的审查重点：
1. **人设管理**：角色口吻是否一致？无厘头情节是否归属正确角色发起？
2. **情节连贯性**：场景过渡是否自然？情节是否与前文矛盾？
3. **逻辑漏洞**：物资数量/时间线/因果链是否自洽？
4. **伏笔检查**：伏笔是否遗漏或生硬？

项目路径：{PROJECT_ROOT}

人物口吻规范（必须严格核对）：
- CharacterA：靴子落地后回归跳脱本性，一本正经说废话，莫名其妙逻辑链，随身带ProductG
- CharacterC：最癫，紫外线又不放假/末日也要美美地
- 主角Protagonist：相对沉稳，自嘲式幽默，不能吃辣，路痴，被噎住/吐槽方
- CharacterB：爱哭，情绪化，行动力强

无厘头情节归属规则：
- ✅ CharacterA/CharacterC：可以主动发起无厘头
- ❌ 主角：不能主动发起无厘头，负责被噎住/吐槽

审查时如发现正文描述与已定稿章节矛盾（如"角色曾去过某地"但grep前文没有），必须标记为重大问题。

输出格式要求：
- 重大问题必须明确标注（⚠️重大漏洞）
- 轻微问题单独列出
- 总体评价要具体，指出1-3 units最需要改进的地方
"""


# ── 审查工具实现 ─────────────────────────────────────────────────────────────

def tool_review_outline(chapter_num: int, outline: str) -> str:
    """审查分级大纲"""
    progress = load_chapters_progress()
    foreshadow = load_foreshadow_table()
    prequel = load_prequel_summary()

    user_prompt = f"""审查第{chapter_num:03d}章的分级大纲。

【待审查大纲】
{outline}

【章节进度总表】
{progress}

【伏笔回收追踪表】
{foreshadow}

【前情摘要合并版】
{prequel}

请从以下维度审查：
1. 情绪节奏是否流畅
2. 伏笔推进是否正确（有没有埋新伏笔、是否回收了待回收伏笔）
3. 核心情节是否合理
4. 与前章衔接是否自然（找前章结尾确认）

返回格式：
```
passed: true/false
情绪节奏问题: [...]
伏笔问题: [...]
情节问题: [...]
衔接问题: [...]
总体评价: "..."
```"""

    return call_llm(consultant_system_prompt(), user_prompt, rounds=2)


def tool_review_chapter(chapter_num: int, chapter_text: str, stage: str = "initial") -> str:
    """审查章节正文"""
    world = load_world_setting()
    rules = load_work_rules()
    foreshadow = load_foreshadow_table()
    prequel_summary = load_prequel_summary()
    recent_chs = load_recent_chapters(chapter_num)
    recent_text = "\n\n".join([f"=== 第{i:03d}章 ===\n{text[:1500]}" for i, text in sorted(recent_chs.items())])

    user_prompt = f"""审查第{chapter_num:03d}章正文（阶段：{stage}）。

【待审查正文】
{chapter_text}

【最近10章已定稿正文（用于核对人物行为轨迹和情节衔接）】
{recent_text}

【世界观与人物设定】
{world}

【工作规范（禁用词表）】
{rules}

【伏笔回收追踪表】
{foreshadow}

【前情摘要合并版】
{prequel_summary}

审查维度：
┌─────────────────┬──────────────────────────────┐
│ 情节连贯性      │ 场景过渡是否自然              │
│ 人物口吻        │ CharacterA/CharacterB/CharacterC说话方式是否一致│
│ 无厘头归属      │ 无厘头是否由CharacterA/CharacterC发起？  │
│ 伏笔检查        │ 伏笔是否遗漏或生硬            │
│ 逻辑问题        │ 物资数量/时间线/因果链        │
│ 重大漏洞        │ 是否存在情节断裂/明显错误     │
│ Day X检查       │ 正文是否出现"Day X"违规？     │
│ 禁用词检查      │ 是否用了AI腔词汇？            │
└─────────────────┴──────────────────────────────┘

⚠️重点：如正文提到"角色去过某地/做过某事"，必须grep最近10章确认是否真实发生过。

返回格式：
{{
  "passed": true/false,
  "重大漏洞": [...],
  "轻微问题": [...],
  "人物口吻问题": {{ "CharacterA": [...], "CharacterB": [...], "CharacterC": [...], "主角": [...] }},
  "伏笔问题": [...],
  "逻辑问题": [...],
  "文风问题": [...],
  "是否可进入人工审阅": true/false,
  "总体评价": "..."
}}"""

    result = call_llm(consultant_system_prompt(), user_prompt, rounds=3)
    return result


def tool_review_feedback(chapter_num: int, chapter_text: str, user_feedback: str) -> str:
    """评估User的反馈是否合理"""
    world = load_world_setting()
    rules = load_work_rules()

    user_prompt = f"""评估User对第{chapter_num:03d}章的反馈是否合理。

【章节正文】
{chapter_text}

【User的原始反馈】
{user_feedback}

【世界观与人物设定】
{world}

【工作规范】
{rules}

评估要求：
- 逐条核对反馈是否合理
- 合理的反馈 → 列入"采纳"清单
- 不合理的反馈 → 列入"不采纳"清单，并说明原因

返回格式：
{{
  "采纳": [
    {{ "反馈": "...", "对应修改点": "..." }}
  ],
  "不采纳": [
    {{ "反馈": "...", "原因": "..." }}
  ]
}}"""

    return call_llm(consultant_system_prompt(), user_prompt)


def tool_check_plot_consistency(chapter_num: int) -> str:
    """逻辑一致性检查"""
    recent_chs = load_recent_chapters(chapter_num)
    recent_text = "\n\n".join([f"=== 第{i:03d}章 ===\n{text[:1500]}" for i, text in sorted(recent_chs.items())])
    foreshadow = load_foreshadow_table()
    progress = load_chapters_progress()
    prequel_summary = load_prequel_summary()

    user_prompt = f"""对第{chapter_num:03d}章进行逻辑一致性全面检查。

【最近10章已定稿正文】
{recent_text}

【伏笔回收追踪表】
{foreshadow}

【章节进度总表】
{progress}

【前情摘要合并版】
{prequel_summary}

检查项：
1. 伏笔待回收：哪些伏笔应该在当前章节被回收？
2. 伏笔已回收：哪些伏笔已经回收了？
3. 时间线：Day X 是否正确递增？有没有时间倒退？
4. 物资变化：物资数量是否与前章衔接？（不能倒退或跳变）
5. 人物状态：角色装备/状态是否与前章一致？

返回格式：
{{
  "伏笔待回收": [...],
  "伏笔已回收": [...],
  "时间线": "正常/异常（说明）",
  "物资变化": "正常/异常（说明）",
  "人物状态": "正常/异常（说明）"
}}"""

    return call_llm(consultant_system_prompt(), user_prompt)


# ── MCP Server 入口 ─────────────────────────────────────────────────────────
def main():
    init_db()

    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool, TextContent

    server = Server("consultant-mcp")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="review_outline",
                description="审查分级大纲的情绪节奏、伏笔推进、情节合理性、章节衔接。",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "chapter_num": {"type": "integer"},
                        "outline": {"type": "string"}
                    },
                    "required": ["chapter_num", "outline"]
                }
            ),
            Tool(
                name="review_chapter",
                description="审查章节正文的人设口吻、情节连贯性、逻辑漏洞、伏笔、禁用词。",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "chapter_num": {"type": "integer"},
                        "chapter_text": {"type": "string"},
                        "stage": {"type": "string", "enum": ["initial", "revision"]}
                    },
                    "required": ["chapter_num", "chapter_text", "stage"]
                }
            ),
            Tool(
                name="review_feedback",
                description="评估User的反馈是否合理，返回采纳/不采纳清单。",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "chapter_num": {"type": "integer"},
                        "chapter_text": {"type": "string"},
                        "user_feedback": {"type": "string"}
                    },
                    "required": ["chapter_num", "chapter_text", "user_feedback"]
                }
            ),
            Tool(
                name="check_plot_consistency",
                description="全面检查章节的伏笔、时间线、物资、人物状态的逻辑一致性。",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "chapter_num": {"type": "integer"}
                    },
                    "required": ["chapter_num"]
                }
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        try:
            if name == "review_outline":
                result = tool_review_outline(arguments["chapter_num"], arguments["outline"])
            elif name == "review_chapter":
                result = tool_review_chapter(
                    arguments["chapter_num"],
                    arguments["chapter_text"],
                    arguments.get("stage", "initial")
                )
            elif name == "review_feedback":
                result = tool_review_feedback(
                    arguments["chapter_num"],
                    arguments["chapter_text"],
                    arguments["user_feedback"]
                )
            elif name == "check_plot_consistency":
                result = tool_check_plot_consistency(arguments["chapter_num"])
            else:
                result = f"[ERROR] 未知工具: {name}"
            return [TextContent(type="text", text=result)]
        except Exception as e:
            return [TextContent(type="text", text=f"[ERROR] {e}")]

    @server.list_prompts()
    async def list_prompts() -> list:
        """Consultant server 不使用 prompts，直接返回空列表"""
        return []

    @server.list_resources()
    async def list_resources() -> list:
        """Consultant server 不使用 resources，直接返回空列表"""
        return []

    import asyncio

    async def run():
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())

    asyncio.run(run())


if __name__ == "__main__":
    main()
