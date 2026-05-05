---
name: novel-chapter-review
description: Systematic paragraph-by-paragraph review for novel chapters — mandatory Step 4 blocking review before user reporting
---

# Novel Chapter Review Skill

## When to Use
Every chapter writing task — mandatory step in the standard workflow (Step 4: 阻断审查).

## Core Principle
**Fix first, report second.** The user does NOT want to see a list of problems for approval. After blocking review, execute the optimal fix directly and only report the summary of what was changed.

## Workflow

### Step 1: Read Materials (Step 2 of standard workflow)
- Read outline + previous chapter + character settings + progress table
- No user reporting needed

### Step 2: Write First Draft (Step 3)
- Write, focusing on core plot (1-2 per chapter max)
- Keep dialogue colloquial, leave hooks at chapter end

### Step 3: Blocking Review (Step 4) — MANDATORY
Read against:
- 本章大纲
- 已定稿的前几章正文
- 世界观与人物设定
- 总纲时间线

**Review every paragraph in order**, checking:

| Check | What to Look For |
|-------|-----------------|
| 📍物资连续性 | Numbers match previous chapter? Can't go backwards |
| ⏰时间线 | Day X consistent with outline/previous chapters? |
| 🔗情节衔接 | Does next paragraph naturally follow? Any breaks or repetition? |
| 🗣️对话逻辑 | Does this line fit the scene? Does the response match the question? |
| 🌍物理地理 | Common sense correct? Impact point → affected area reasonable? |
| 📡消息来源 | If "radio unclear" earlier, can later dialogue cite it clearly? |
| 🗺️地名一致性 | 本章所有地名是否与已定稿章节一致？虚拟地名写法必须与前文统一 |
| 🌧️天气预报 | Forecast time matches actual rain time? |
| 🔋设施铺垫 | Rain collection/solar mentioned before used later? |
| 🎯大纲核对 | This paragraph in scope? Core plot missed or deviated? |
| 👤人物认知 | 角色是否对已知道的事实表现出惊讶/追问？已知事实不能重复质疑 |
| 🎭角色行为触发 | 角色标志性动作只在合理场景触发，不合场景出现 = P1错误 |

**🔁 跨章节情节递进检查（强制！）**

**检查方法**：写/审本章前，先grep前3章**相同类型的情节**：
- 如果同类情节已在前章完整写完 → 本章必须**直接切到消化结果的下一阶段**，不能再走一遍相同流程
- 本章的正确结构：**消化 → 追问细节 → 立刻进入下一个真实危机**
- "递进"的判断标准：本章结束时，读者知道的比上章结束时多了一个新的危机或真相，不是重复已知的反应

**Priority classification:**
- Priority 1 (严重): Logic errors, repetition, timeline/物资 contradictions
- Priority 2 (中等): Physics/geography errors, source inconsistencies, forecast mismatches  
- Priority 3 (轻微): Missing foreshadowing

**Execute ALL fixes immediately. Do not present problem list to user first.**

### ⚠️ 顾问审查（review_chapter）返回后的处理流程

**正确流程**：
1. 顾问审查返回后，**立即判断**：问题是否需要MCP revise（大改/结构调整）还是terminal patch（小改）？
2. 如果需要MCP revise → 直接调用 `revise_chapter`，将所有顾问问题合并为**一次** revise prompt 发出
3. revise返回后 → 检查"未完待续"→ 报告用户"已按顾问意见修改完成，字数X"
4. **不需要**每次问题都问用户"是否调用MCP"

**合并revise的好处**：避免多次MCP调用导致上下文膨胀/版本混乱；用户不需要逐条审批；符合skill声明的阻断式审查原则。

**何时需要问用户**：只有当顾问的方案涉及多个选项且含义不同（如方案A/B描述不一致）时才需要确认。

### Step 4: Report to User
After fixing, report:
- What was fixed (bullet list, brief)
- New character count
- Ask: any other changes needed?

### Step 5: Final Review (Step 5 - seq MCP)
Only if user explicitly asks, or if logical issues remain.

## Key Anti-Pattern
❌ Present a list of problems → wait for user approval → fix one by one
✅ Review thoroughly → apply optimal fixes → report summary only

### 顾问审查注入规则（强制）
**调用 `mcp_consultant_review_chapter` 前必读**：`references/consultant-injection-rules.md`

核心原则：顾问的逻辑质疑要核验，顾问的修复方案只是参考，**顾问可能出错**（用户会纠正）。

## 双重核对（强制，不可跳过）

每次写章节初稿之前或发送章节给用户审阅之前，必须完成以下两项核对，**不允许跳过**：

#### 核对A：与已定稿章节核对
- [ ] 时间线是否与已定稿章节衔接？（本章 Day X 是否与上章一致？）
- [ ] 是否有情节重复？（同一事件不能写两遍）
- [ ] 人物状态是否连续？（物资数量是否与上章末尾一致）
- [ ] 冷库温度/柴油/通讯状态是否自洽？

#### 核对B：与分卷大纲核对
- [ ] 本章核心情节是否在大纲范围内？
- [ ] 如需调整情节，必须先更新大纲再写初稿，**不能先写后改大纲**
- [ ] 确认本章节在分卷大纲中的"已写章节"列已标记

## 发送前自查（用户要求"发我看看"时）

用户要求查看章节正文时，**先快速自查再发送**：

1. 上一章末尾的物资/时间/人物状态是否与本章开头衔接？
2. 本章中是否有明显逻辑矛盾？（数量跳变、地点错误、人物状态矛盾）
3. 对话是否口语化？
4. 是否有已知的之前修正过的同类问题？

发现问题时**先修再发**，不要等问题列表发给用户等批复。

#### 核对C：新增条目先grep确认不存在
用户提出"把这个道具加到物资表/伏笔表"时，**先grep目标文件**：
- 搜到记录 → 已是最新，无需重复添加，告知用户"已在表中"
- 搜不到 → 再按用户要求新增

## 设备道具来源规范（高频问题）

| 问题类型 | 典型错误 | 修正方向 |
|---------|---------|---------|
| 望远镜突然出现 | "背包里翻出望远镜" | 望远镜不是随身物品，改用手机摄像头超长焦模式 |
| 检测仪突然出现 | "从背包里拿出检测仪" | 检测仪来源要可追溯，改为"万用表+手机监测APP" |
| 工具在错误位置 | "攥紧对讲机"但两人都在室内 | 对讲机是对外通讯，危机关头两人同在室内应写"攥紧拳头" |

## 顾问审查后处理流程

1. 顾问提出的问题**先判断是否和大纲冲突**——顾问不知道当前章节对应的分卷大纲是否已修改

### ⚠️ 顾问方案理解校验（强制）

**症状**：顾问给出"方案A/方案B"等多选项时，用户的实际选择可能与顾问描述不完全一致，必须在执行前向用户确认理解。

**补丁逻辑自检（强制）**：
- 当用户的方案澄清涉及"保留原版"时，必须同时检查下游段落是否也需要跟着回滚
- 典型症状：改了一处，另一处没改，导致上下文矛盾

**顾问要求核验前文时的处理**：
- 顾问返回"重大漏洞3：需确认前文锚点"时，**立即grep验证**，不汇报给用户等指示
- grep结果：如果前文吻合 → 直接确认，无需通知；如果前文矛盾 → 立即patch修正并汇报

**执行前复述规则（不可跳过）**：
1. 收到多选项后向用户说明每个选项含义
2. 用户选择后用自己的话复述确认
3. 确认后执行，**每次只改用户明确要求的那一处**
4. 改完后再问"还有别的要改吗"，不要一次改完所有相关段落再一起报告

## 去AI味规范（高频问题）

| 问题类型 | 典型错误 | 修正方向 |
|---------|---------|---------|
| 静电原理 | "帆布桶不安全/会破" | 正确原因：静电打火 |
| 加油站招牌 | 加油站通常是红色非绿色 | 写实为红色 |
| Day标记 | 角色对话中说"Day X" | 改为"第五天"/"后天"等日常说法 |
| 物资数量 | 家用车油箱描述为100升 | 实际40-60升 |
| 工具位置 | "回去拿"但工具本就在车上 | 上下文一致性检查 |
| 破折号断句 | "够撑到XX吗？够撑到——我不知道" | 检查破折号是否意外截断句子 |

## MCP顾问Server调试经验

### 教训：参考材料体积不能超过被审正文

**症状**：顾问审查时老审错章节（把前几章当主角审，而非当前章节）
**根因**：参考材料5章全文约18K tokens，而待审正文才3.7K，比例5:1，LLM必然以大为先
**修复**：
1. `config.py`：`RECENT_CHAPTERS_FULL` 从5改为2（仅加载1-2章全文够核对衔接，不要调大）
2. `consultant_server.py` prompt结构：待审正文用★框放到最前，参考材料放后面并明确标注"仅作背景参考"

### MCP Server重启注意
stdio模式的MCP server收到stdin关闭信号会立即退出，hermes-agent的MCP client会自动重启，**不需要手动重启**，等待gateway自然拉起即可。

---

## 重要提醒
- Character count standard: **正文字数** = 正文总字符数（含标点，不含标题行和结尾"（未完待续）"标记）
- Never generate 重构版 until user says "定稿"
- Never sync to 重构版 until user says "定稿"
- 上下文压缩后，章节状态可能丢失。发送章节给用户前，**必须先做发送前自查**，防止绕过审查流程直接发送
