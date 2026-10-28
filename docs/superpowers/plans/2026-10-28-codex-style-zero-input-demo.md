# Codex 式零输入管束 Demo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Demo 改成 Codex 式左侧导航+右侧对话/内嵌审核预览，并实现用户零参数输入的一键设计。

**Architecture:** 保留 PyQt5 和现有审核业务对象，重构 `DesignWindow` 的布局与入口。左侧栏只承载开始、设置、历史和进度；主区中的预览卡复用现有表格及审核按钮。内置模拟数据通过既有数据库默认值和历史数据加载，不在 UI 显示输入参数。

**Tech Stack:** Python 3、PyQt5、unittest、SQLite

**Spec:** `docs/superpowers/specs/2026-10-28-codex-style-zero-input-demo-design.md`

## Global Constraints

- 不修改 `E:/Homework/AALB/ACode/DongLanpec` 生产交付仓库。
- 主界面不得出现设备、产品型式、DN 和文件输入控件。
- 只在预览表或对话指令中修改参数，修改后必须重新审核。
- 保留用户已有 draw.io 备份文件，不加入版本库。

## Review Focus

- 内置模拟数据启动后必须能直接产生待审核预览。
- 主界面不能再泄漏设备、产品型式、DN 或文件选择入口。
- 对话数值修改必须调用真实 `ReviewSession.apply_edit()` 并撤销审核状态。
- 完成四阶段后预览不能再作为空卡打开。
- 较小分辨率下左侧栏不能挤占审核表主要空间。

---

### Task 1: 零输入启动契约

**Files:**
- Modify: `tests/test_window.py`
- Modify: `window.py`

**Interfaces:**
- Produces: `DesignWindow.start_demo_design() -> None`

- [ ] Write failing tests proving the main window has no `QComboBox`/`QDoubleSpinBox`, exposes one start button, and `start_demo_design()` produces a real review session and visible preview.
- [ ] Run `python -m unittest tests.test_window -v` and verify RED.
- [ ] Implement `start_demo_design()` with internal `DocumentBundle([])`, equipment id `DEMO-E-1001`, product type `AEU`, and DN `700`, without adding any corresponding UI input.
- [ ] Run the same command and verify GREEN.
- [ ] Commit the task.

### Task 2: Codex 式宽屏布局

**Files:**
- Modify: `tests/test_window.py`
- Modify: `window.py`
- Modify: `main.py`

**Interfaces:**
- Consumes: Task 1 `start_demo_design()`
- Produces: 左侧栏 `self.sidebar`、右侧主区 `self.main_panel`、内嵌 `self.review_panel`

- [ ] Write failing tests for minimum/default size, sidebar width, inline review placement, and absence of the old horizontal review splitter.
- [ ] Run `python -m unittest tests.test_window -v` and verify RED.
- [ ] Rebuild `_build_ui()` as a fixed-width sidebar plus a flexible right main panel; move the review card between conversation and composer; maximize the normal launcher window.
- [ ] Run the same command and verify GREEN.
- [ ] Commit the task.

### Task 3: 对话直接修改预览

**Files:**
- Modify: `tests/test_window.py`
- Modify: `window.py`

**Interfaces:**
- Produces: `DesignWindow.apply_chat_request(text: str) -> bool`

- [ ] Write a failing test that sends `换热管中心距 S 改为 34` during the second stage and asserts the real parameter becomes `34` with status `待审核`.
- [ ] Run the focused test and verify RED.
- [ ] Implement safe current-stage numeric parameter matching; nonmatching text remains a note and derived/noneditable values are rejected with a concise reply.
- [ ] Run `python -m unittest tests.test_window -v` and verify GREEN.
- [ ] Commit the task.

### Task 4: 文档、截图与最终验证

**Files:**
- Modify: `README.md`
- Modify: `docs/操作手册.md`
- Regenerate: `docs/界面预览.png`
- Regenerate: `docs/界面预览-审核不通过.png`

**Interfaces:**
- Consumes: Tasks 1–3

- [ ] Update instructions so the only normal start path is double-click launcher then click `开始管束设计`.
- [ ] Regenerate and visually inspect the default and failed-review screenshots at the larger size.
- [ ] Run `python -m unittest discover -s tests -v`; expect all tests PASS.
- [ ] Verify the production repo is clean and the Demo has only the draw.io backup left untracked.
- [ ] Commit the task.
