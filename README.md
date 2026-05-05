# 小说AI写作系统 · 通用模板

> 通用多Agent协作长篇写作工作流，适合任何长篇小说项目。

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
├── 写作流程规范.md                    # 章节全流程规范（写→审→改→定稿）
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
  DEEPSEEK_API_KEY: "sk-you...here"   # ← 替换这里
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

## 三、章节写作标准流程

> 核心原则：**写 → 审 → 改 → 用户审阅 → 定稿**。每一步不可跳过。

### Step 1：写大纲

**入口**：分卷大纲 XML 中对应章节的标签（如 `#chapter-N`）

**操作**：

1. 读取对应章节标签内容（PlotPoint + EndPoint）
2. 确认前3章时间线和已定稿章节末尾状态
3. 加载写作规则 + 人物设定 + 群聊场景（如有）
4. 生成结构化分级大纲
5. 顾问审查大纲（`mcp_consultant_review_outline`）

**大纲审查通过后** → 进入 Step 2

---

### Step 2：写初稿

**工具**：`mcp_writer_write_chapter(chapter_num, outline)`

**Prompt 注入顺序**（writer_server.py 自动处理）：

| 顺序 | 内容                       | 来源           |
| --- | ------------------------ | ------------ |
| 1   | 分级大纲（PlotPoint）          | 大纲文件        |
| 2   | 最近章节正文（最近2章全文+更早各600字预览） | 本地文件        |
| 3   | 前情摘要合并版                  | 本地文件        |
| 4   | RAG召回片段（top_k=4，不限章节）    | rag_index.json |
| 5   | 世界观与人物设定                 | 设定库相关标签    |

**写前必查（双重核对）**：

- [ ] 本章时间线是否与上章末尾衔接？
- [ ] 是否有情节与已定稿章节重复？
- [ ] 人物状态/物资数量是否与上章一致？

**禁止**：

- ❌ 跳过顾问直接finalize
- ❌ 跳过审查直接报告"可以直接定稿"
- ❌ 用户未审阅就自行finalize

---

### Step 3：顾问审查（阻断审查）

**工具**：`mcp_consultant_review_chapter(chapter_num, chapter_text, stage=initial)`

**注入材料**：

```
【本章大纲核心PlotPoint】（从大纲读取）
【地名虚拟化对照表】（如有）
【前3章已出现的群ID/物资细节】（如有）
```

**审查返回后处理**：

| 问题类型      | 处理方式                         |
| --------- | ---------------------------- |
| 单一方案/同向问题 | 直接调用 `revise_chapter` 一次，发出所有问题 |
| 多方案且含义不同  | 向用户说明，等用户选择                  |
| 顾问建议含不存在的人名/地名 | grep验证，跳过不存在项，向用户说明 |

**所有顾问建议执行后，仍必须等用户审阅正文后才能finalize**

---

### Step 4：执行修改

**小改（1-3句/个别段落）**：terminal `patch`，直接执行，不调MCP

**大改（结构/新增情节）**：调用 `mcp_writer_revise_chapter`

**revise 后必须操作**：

1. 检查输出末尾是否有"未完待续"→ patch删掉
2. 将revise版正文写入章节文件
3. 向用户展示修改摘要，请用户审阅

---

### Step 5：用户审阅 → 说"定稿"

**用户审阅后确认** → 调用 `mcp_writer_finalize_chapter(chapter_num)`

---

## 四、定稿后对齐清单（每步必执行）

| 步骤 | 操作                           | 文件位置           |
| --- | ---------------------------- | -------------- |
| 1   | 章节进度总表 → ✅定稿                | 设定库 `#chapter-progress` |
| 2   | 章节统计总览 → 已定稿数+1、字数更新         | 设定库 `#stats`     |
| 3   | 最后更新日期                        | 设定库 `#meta`      |
| 4   | 前情摘要合并版 → 包含新章节摘要              | `前情摘要合并版.md`   |
| 5   | 伏笔档案 → 已回收/已埋设                | 设定库 `#foreshadowing` |
| 6   | 人物设定库 → 新人物已添加                | 设定库 `#personas`  |
| 7   | 物资消耗记录 → 已更新（如涉及）             | 设定库 `#supplies`  |
| 8   | 章节标题 → ≥2汉字                    | 正文标题行         |
| 9   | RAG索引 → 更新向量数据库               | `.mcp/rag.py` + rag_index.json |

**汇报规则**：定稿后**不等待追问**，主动在同一条消息里逐项汇报完成状态。

---

## 五、修改工作流（小改 vs 大改）

| 场景        | 方式                      |
| --------- | ----------------------- |
| 改写/删除1-3句 | terminal `patch`         |
| 加新情节（当前文件没有的） | `revise_chapter`         |
| 用户说"只改结尾" | terminal `patch`         |
| 时间线修正+新增伏笔 | `revise_chapter`         |
| 删除5+段重复/冗余 | `patch`，从后往前，每2-3段验证一次 |

**patch 删内容规范**：

1. `read_file` 精确行号范围
2. old_string 覆盖足够上下文，确保唯一匹配
3. 删完读文件验证

**patch 失败处理**：

- Found 2+ matches → 停手，加大上下文重新匹配
- 不得 replace_all

---

## 六、顾问审查注入规则

调用 `review_chapter` 前必须注入：

```
【本章大纲核心PlotPoint】
【地名虚拟化对照表】（如有）
【前3章群聊ID/物资细节】（如有）
```

**顾问可能出错**：顾问建议中出现具体人名/地名/道具名时，必须先 grep 验证该要素是否存在于当前章节。不存在则跳过。

---

## 七、常见坑检查清单

### 每章写前必问

- [ ] 这章情节是否在上章已经写完？（不能重复）
- [ ] 新角色首次出场是否有来历说明？
- [ ] 物资数量是否与上章末尾一致？
- [ ] 对话"友好度"是否符合角色关系？
- [ ] 真实地名是否已替换为虚拟地名？（如有）

### 跨章节引用验证

引用其他章节具体细节（人名/地名/物品/事件）之前：

1. grep该章节原文，确认该细节**确实存在**
2. 确认具体措辞（避免同义改写后产生歧义）
3. 确认上下文支持引用方向

### patch 多位置修改顺序

**从后往前**（bottom-to-top），防止行号偏移导致前面修改影响后面匹配。

---

## 八、代码结构（参考）

### 8.1 writer_server.py 核心逻辑

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
    outline_text = load_outline(chapter_num)   # 读大纲
    prompt = build_prompt(outline_text)        # 构造生成Prompt
    chapter_text = call_llm(prompt)            # 调用LLM
    write_file(chapter_text)                   # 写入章节文件
    return chapter_text
```

### 8.2 consultant_server.py 核心逻辑

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

### 8.3 rag.py（可选，RAG知识库）

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

## 九、文件路径规范（绝对路径，禁止相对路径）

| 用途    | 路径       |
| ----- | -------- |
| 小说根目录 | 项目根目录    |
| 正文章节  | `正文章节/`  |
| 大纲/设定 | `大纲及设定/` |
| RAG索引  | `.mcp/rag_index.json` |

---

## 十、常见问题

**Q: MCP连接失败？**
检查writer_server.py是否在运行，端口是否被占用，API Key是否正确。

**Q: 生成的章节只有几百字？**
检查大纲是否完整传入（有些实现会用Context Agent压缩大纲导致信息丢失）。

**Q: 审查指出的问题修复后又有新问题？**
正常，用revise_chapter多轮迭代，每次修复后重新审查。

**Q: 如何处理架空世界观？**
确保小说设定中物理逻辑、社会逻辑自洽，顾问会检查这类常识性漏洞。
