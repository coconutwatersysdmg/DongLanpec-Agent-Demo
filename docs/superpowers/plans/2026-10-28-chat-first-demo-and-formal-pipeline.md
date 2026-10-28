# Chat-first Demo 与正式 Pipeline 修订 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 Demo 改成默认只显示对话、仅在需要审核时展开审核抽屉的交互，并把 draw.io 图改成正式软件的管束 Agent 工作流。

**Architecture:** 保留现有 `ReviewSession`、规则校验、DeepSeek 接入和 SQLite Demo 数据层，只重排 PyQt 主窗口的呈现状态。审核表格仍是同一实例，由窗口统一控制展开、收起和重开；正式 Pipeline 图独立描述生产软件的数据流转、数据库读取、人工审核和最终入库，不展示 Demo 的上传与 SQLite 实现细节。

**Tech Stack:** Python 3、PyQt5、unittest、draw.io XML

**Spec:** `docs/2026-10-28-管束AI单窗口审核Demo设计.md`

## Global Constraints

- 不修改 `E:/Homework/AALB/ACode/DongLanpec` 生产交付仓库。
- 保留用户在 draw.io 中已改的标题“管束 AI Agent”和已删除的副标题。
- Demo 仍可选文件或示例包，但这些不得出现在正式软件 Pipeline 中。
- 参数修改、采用推荐值后必须重新审核；审核通过后仍需用户确认。
- API Key 不写入代码、文档、测试或截图。

## Review Focus

- 窗口刚启动时审核区不能占用对话空间。
- Agent 准备好结构化数据后，审核区必须自动出现并能被用户收起。
- 收起审核区后必须有明显且可用的“查看审核”入口。
- 审核失败、采用推荐值和切换阶段不得丢失原有红色标记、重审和确认闸门。
- 正式 Pipeline 不得出现“上传文档”、“模拟上游”、“独立演示库”或“SQLite”。

---

### Task 1: Chat-first 审核抽屉状态

**Files:**
- Modify: `tests/test_window.py`
- Modify: `window.py`

**Interfaces:**
- Consumes: 现有 `DesignWindow._accept_prepared()` 和 `DesignWindow.render_stage()`
- Produces: `DesignWindow.set_review_drawer_visible(visible: bool) -> None`

- [ ] **Step 1: Write the failing GUI tests**

添加三个行为测试：新窗口默认隐藏审核区；准备好数据后自动展开；收起后可用顶部入口重新展开。

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m unittest tests.test_window -v`

Expected: FAIL because the review panel is permanently present and there is no drawer visibility API.

- [ ] **Step 3: Implement the minimal drawer behavior**

保留 `QSplitter`，将审核面板保存为 `self.review_panel`，添加收起按钮和可重开的 `self.review_toggle_button`，并在 `_accept_prepared()` 中展开。

- [ ] **Step 4: Run tests and verify GREEN**

Run: `python -m unittest tests.test_window -v`

Expected: all window tests PASS.

### Task 2: 对话优先的操作布局

**Files:**
- Modify: `window.py`
- Modify: `docs/2026-10-28-管束AI单窗口审核Demo设计.md`
- Modify: `docs/操作手册.md`

**Interfaces:**
- Consumes: Task 1 的审核抽屉控制
- Produces: 默认单对话面的主窗口和收敛到输入区的 Demo 操作入口

- [ ] **Step 1: Rework the layout without changing domain behavior**

将对话区作为默认主视图，文件/示例、设备与开始处理控件收敛到对话输入区；保留 DeepSeek 设置、历史方案和处理状态。

- [ ] **Step 2: Update user-facing documentation**

明确“Demo 上传是演示入口，正式软件从数据流转/数据库接收”，并说明如何展开、收起和重新打开审核抽屉。

- [ ] **Step 3: Run the GUI regression suite**

Run: `python -m unittest tests.test_window tests.test_review_session tests.test_review_findings -v`

Expected: all tests PASS.

### Task 3: 正式软件 Pipeline draw.io

**Files:**
- Modify: `docs/管束AI审核流-Pipeline.drawio`
- Regenerate: `docs/管束AI审核流-Pipeline预览.svg`

**Interfaces:**
- Consumes: 用户修改后的三页 draw.io 文件
- Produces: 正式管束模块的总体 Pipeline、四阶段数据流和状态流转图

- [ ] **Step 1: Revise the first page in place**

改为“数据流转/数据库接收 → 基础上下文组装 → Agent 识别与建议 → 联动校验 → 人工审核迭代 → 存入数据库”。

- [ ] **Step 2: Revise the data-flow and state pages in place**

数据源改为总 Agent/数据空间流转、前置模块数据库、程序默认和历史产品；状态改为等待数据、装载、Agent 处理、待人工审核、待确认、入库和完成。

- [ ] **Step 3: Export and inspect the SVG**

用 draw.io 桌面端导出预览，确认三页文字不截断、连线无遮挡，且不存在 Demo 术语。

### Task 4: 全量验证与交付检查

**Files:**
- Modify if needed: `README.md`
- Modify if needed: `docs/界面预览.png`
- Modify if needed: `docs/界面预览-审核不通过.png`

**Interfaces:**
- Consumes: Tasks 1–3
- Produces: 可演示、可说明、可继续编辑的最终交付

- [ ] **Step 1: Run the complete automated suite**

Run: `python -m unittest discover -s tests -v`

Expected: all tests PASS with no traceback.

- [ ] **Step 2: Run a launcher smoke test**

通过启动脚本打开 Demo，检查默认对话面、审核抽屉和收起/重开路径。

- [ ] **Step 3: Check repository boundaries**

确认只有 Demo 目录变更，`E:/Homework/AALB/ACode/DongLanpec` 没有新增 AI 代码或未预期修改。

