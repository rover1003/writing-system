# 小说AI写作系统 · 通用模板

> 脱胎自《重生之我在末日囤了十万袋沙棘原浆》实战积累，剥离所有小说特定内容，保留可复用的代码骨架、工作流规范和审查规则。

---

## 一、系统架构

```
写作系统/
├── mcp/                          # MCP服务器（AI工具集）
│   ├── writer_server.py           # 写章节+写大纲（调用LLM生成正文）
│   ├── consultant_server.py       # 顾问审查（逻辑/口吻/伏笔检查）
│   ├── rag.py                    # RAG知识库（向量检索，为LLM提供上下文）
│   └── config_in_container.yaml   # MCP服务配置（API Key、模型、路径）
├── skills/                        # Skill工作流（流程规范文档）
│   ├── novel-chapter-workflow.md  # 章节修改工作流（小改/patch/大改/revise规则）
│   └── novel-chapter-review.md    # 顾问审查规范（审查清单、检查点）
└── README.md                      # 本文档
```

### 核心工具链

| 工具                       | 用途                    | 调用方式                                                               |
| ------------------------ | --------------------- | ------------------------------------------------------------------ |
| `write_chapter`          | 根据分级大纲写章节初稿（≥4000字）   | `mcp_writer_write_chapter(chapter_num, outline)`                   |
| `revise_chapter`         | 根据反馈修改章节（全章重写）        | `mcp_writer_revise_chapter(chapter_num, feedback[])`               |
| `patch_chapter`          | 局部patch修改（不重写全章）      | `mcp_writer_patch_chapter(chapter_num, patches[])`                 |
| `finalize_chapter`       | 定稿：写摘要、更新进度表、追加合并摘要   | `mcp_writer_finalize_chapter(chapter_num)`                         |
| `write_outline`          | 根据分卷大纲章节原文，写分级大纲      | `mcp_writer_write_outline(chapter_num)`                            |
| `review_chapter`         | 顾问审查：检查逻辑漏洞/口吻/伏笔/禁用词 | `mcp_consultant_review_chapter(chapter_num, text, stage)`          |
| `check_plot_consistency` | 全面检查伏笔/时间线/物资/人物状态一致性 | `mcp_consultant_check_plot_consistency(chapter_num)`               |
| `review_feedback`        | 评估修改意见是否合理            | `mcp_consultant_review_feedback(chapter_num, text, user_feedback)` |

---

## 二、配置（首次使用必读）

### 2.1 API Key

编辑 `mcp/config_in_container.yaml`，找到 `DEEPSEEK_API_KEY`，替换为你的真实Key：

```yaml
env:
  DEEPSEEK_API_KEY: "sk-your-real-key-here"   # ← 替换这里
```

### 2.2 路径配置

`config_in_container.yaml` 中的路径为容器内路径，需根据实际情况修改：

```yaml
novels_workspace: "${WORKSPACE}/正文章节/"       # ← 章节文件存放目录
outline_dir: "${WORKSPACE}/大纲/"                 # ← 大纲文件目录
summary_dir: "${WORKSPACE}/前情摘要/"             # ← 章节摘要目录
```

> **首次使用前**：确认上述目录存在，或在配置中改为实际存在的路径。

### 2.3 启动MCP服务

```bash
# writer_server（写章节）
python3 mcp/writer_server.py

# consultant_server（审查）
python3 mcp/consultant_server.py
```

两个服务可以同时运行，互不干扰。

---

## 三、标准写作流程

### 3.1 章节写作流程（全程）

```
分卷大纲 → 写分级大纲 → 写初稿 → 顾问审查 → 用户确认修改点
→ patch/revise → 顾问再审（如需要）→ 用户最终确认 → finalize
→ 更新XML大纲进度表 → 完成
```

**各阶段说明：**

| 阶段       | 执行者                                | 输出          |
| -------- | ---------------------------------- | ----------- |
| ① 写分级大纲  | `write_outline`                    | 分级大纲文本      |
| ② 写初稿    | `write_chapter`                    | ≥4000字正文    |
| ③ 顾问审查   | `review_chapter(stage="initial")`  | 问题列表（致命/轻微） |
| ④ 用户确认   | —                                  | 确认修改范围      |
| ⑤ 修改章节   | `patch_chapter` 或 `revise_chapter` | 修改后正文       |
| ⑥ 定稿     | `finalize_chapter`                 | 摘要+进度表更新    |
| ⑦ 用户最终审阅 | —                                  | 确认发布        |

### 3.2 修改类型判断

```
小改（一两句话/个别段落）  → 直接patch，不调MCP
大改（结构/新增情节）      → revise_chapter，调MCP全章重写
用户明确说"只改结尾"      → 只改那个位置，其他不动
删除内容                   → 必须结合上下文修改，必要时补过渡句
```

### 3.3 强制检查点

**revise之后必须先写入文件，用户审阅确认后才能finalize。**

```
revise输出 → 写入文件 → 用户看文件确认 → finalize
```

禁止顺序：

```
revise → finalize（中间没有用户确认步骤）
```

---

## 四、Skill工作流详解

### 4.1 novel-chapter-workflow.md（章节修改工作流）

**核心原则：**

- 小改直接patch，不调MCP
- 大改/结构修改调revise_chapter
- 修改必须结合上下文，不能简单粗暴删除了事
- 删除内容后检查段落衔接，必要时补过渡句

**patch判断标准（满足任一即用patch）：**

- 错别字、病句
- 一两句话的增删
- 个别段落的调整
- 逻辑自洽的小调整（时间线矛盾、物资数量不一致）

**revise判断标准（满足任一即用revise）：**

- 新增情节/场景
- 大量对话重写（超过3处）
- 人物心理/性格转变
- 章节结构重组

### 4.2 novel-chapter-review.md（顾问审查规范）

**审查清单（每章必查）：**

| 检查项   | 说明                 |
| ----- | ------------------ |
| 人设口吻  | 对话是否符合人物设定，避免AI腔   |
| 情节连贯性 | 事件发展是否符合因果链        |
| 时间线逻辑 | 关键节点是否自洽，Day标记是否正确 |
| 物资数量  | 消耗/囤货数量与前文是否一致     |
| 伏笔    | 前文伏笔是否正确回收         |
| 禁用词   | 禁用"未完待续"、AI高频词等    |

**审查原则：**

- 顾问是防御性检查，发现问题必须指出
- 不接受"差不多得了"——逻辑漏洞必须修复
- 修复后需要用户人工审核一遍

---

## 五、XML标签体系（可选）

`skills/novel-xml-tagging-system.md` 描述了XML标签化体系，用于：

- 大纲按标签模块化（`#chapter-27`、`#supplies`、`#personas`等）
- writer按需加载特定标签，避免情节越界泄露
- 物资/人物/伏笔集中管理

> 新项目建议：**跳过XML体系，直接用Markdown文件管理大纲和设定。** XML体系适合多agent协作的大型项目，复杂度较高。

---

## 六、代码结构（参考）

### 6.1 writer_server.py 核心逻辑

```python
# 工具注册
@writer_server.list_tools()
def list_tools():
    return [
        write_chapter_tool,   # 写初稿
        revise_chapter_tool,  # 全章重写
        patch_chapter_tool,   # 局部修改
        write_outline_tool,    # 写分级大纲
        finalize_chapter_tool, # 定稿
    ]

# 核心流程：读大纲 → 构造Prompt → 调用LLM → 写文件
def write_chapter(chapter_num, outline):
    outline_text = load_outline(chapter_num)   # 读XML大纲
    prompt = build_prompt(outline_text)        # 构造生成Prompt
    chapter_text = call_llm(prompt)            # 调用DeepSeek
    write_file(chapter_text)                   # 写入章节文件
    return chapter_text
```

### 6.2 consultant_server.py 核心逻辑

```python
@consultant_server.list_tools()
def list_tools():
    return [
        review_chapter_tool,             # 审查章节
        check_plot_consistency_tool,     # 逻辑一致性检查
        review_feedback_tool,            # 评估修改意见
    ]

def review_chapter(chapter_num, text, stage):
    # 按审查清单逐项检查
    # 返回致命问题 + 轻微问题列表
    issues = check_logic(text)
    issues += check_dialogue(text)
    issues += check_foreshadowing(text)
    return issues
```

### 6.3 rag.py（可选，RAG知识库）

```python
def build_index(chunks: list[str]):
    """将章节文本分块，构建向量索引"""
    embeddings = get_embeddings(chunks)  # Ollama embedding
    index = faiss.IndexFlatIP(len(embeddings[0]))
    index.add(embeddings)
    return index

def retrieve(query: str, top_k: int = 5):
    """语义检索，返回最相关的章节片段"""
    query_emb = get_embeddings([query])
    scores, indices = index.search(query_emb, top_k)
    return [chunks[i] for i in indices[0]]
```

---

## 七、常见问题

**Q: MCP连接失败？**
检查writer_server.py是否在运行，端口是否被占用，API Key是否正确。

**Q: 生成的章节只有几百字？**
检查outline是否完整传入（有些实现会用Context Agent压缩outline导致信息丢失）。

**Q: 审查指出的问题修复后又有新问题？**
正常，用revise_chapter多轮迭代，每次修复后重新审查。

**Q: 如何处理断网设定？**
确保小说设定中"断网后无法下载"等物理逻辑一致，顾问会检查这类常识性漏洞。

---

## 八、清洗记录

| 源文件                         | 清洗内容                     |
| --------------------------- | ------------------------ |
| `writer_server.py`          | 删除所有人名/地名/产品名/具体数值/章节号引用 |
| `consultant_server.py`      | 同上                       |
| `rag.py`                    | 删除硬编码的小说人物/地名列表          |
| `config_in_container.yaml`  | API Key替换为占位符            |
| `novel-chapter-workflow.md` | 删除所有小说特定内容，保留通用工作流框架     |
| `novel-chapter-review.md`   | 删除所有小说特定内容，保留审查规范        |

> **注意**：清洗后的代码已去除小说特定内容，但结构注释中可能仍有残留引用（如"某小说第X章"），使用时请以实际代码逻辑为准。
