# 单一保留按钮与 Codex 风格界面 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将四阶段预览改为单一“保留”操作，并把主窗口进一步调整为 Codex 式宽屏对话与预览界面。

**Architecture:** 保留 `ReviewSession` 的规则审核、版本失效和数据库保存语义，在 `DesignWindow` 中把审核与确认编排合并为 `save_current_stage()`。左侧阶段控件改为可点击按钮；预览卡只在错误时展开错误详情，表格和整体样式在现有 PyQt5 单窗口上重做。

**Tech Stack:** Python 3、PyQt5、unittest、SQLite

**Spec:** `docs/superpowers/specs/2026-10-29-single-save-stage-flow-design.md`

## Global Constraints

- 每个阶段底部只显示一个主操作按钮 `保留`。
- 保留时自动校验；失败不得弹确认、保存或跳转。
- 校验通过后必须经用户弹窗确认，才保存并进入下一阶段。
- 已到达阶段可从左侧回看修改；未到达阶段不可提前打开。
- 不修改 `E:/Homework/AALB/ACode/DongLanpec` 正式项目。

## Review Focus

- 用户取消确认时不得写库或跳转。
- 校验失败时错误参数必须标红并提供可用推荐值。
- 修改已保存的旧阶段必须撤销它及后续阶段的旧快照。
- 完成最后阶段后仍能从左侧回看，但不能产生空预览。
- 左侧点击未到达阶段时不得绕过顺序约束。

---

### Task 1: 单按钮保留闭环

**Files:**
- Modify: `tests/test_window.py`
- Modify: `window.py`

**Interfaces:**
- Produces: `DesignWindow.save_current_stage() -> None`

- [ ] 写失败测试：底部只有 `保留`；错误值点击后标红且未写库；正确值确认后写库并进入下一阶段；取消确认保持原阶段。
- [ ] 运行 `python -m unittest tests.test_window -v`，确认因单按钮行为未实现而失败。
- [ ] 实现 `save_current_stage()`，内部调用真实 `ReviewSession.run_review()`；仅通过时调用 `QMessageBox.question()` 和 `confirm_and_advance()`。
- [ ] 删除旧的审核、确认和返回按钮；错误区默认隐藏，仅在校验失败时显示。
- [ ] 运行窗口测试并提交。

### Task 2: 左侧阶段回看和修改

**Files:**
- Modify: `tests/test_window.py`
- Modify: `window.py`

**Interfaces:**
- Consumes: Task 1 `save_current_stage()`
- Produces: `DesignWindow.open_stage(index: int) -> None`

- [ ] 写失败测试：保存第一阶段后可点回第一阶段；第三、四阶段尚未到达时不可打开；修改旧阶段后后续快照失效。
- [ ] 运行窗口测试确认 RED。
- [ ] 将进度标签替换为可点击阶段按钮，根据当前阶段和 `approved` 状态更新可用范围。
- [ ] 实现 `open_stage()` 并复用 `ReviewSession.go_to_stage()`，旧阶段编辑继续使用既有依赖失效逻辑。
- [ ] 运行窗口测试并提交。

### Task 3: Codex 风格视觉与交付更新

**Files:**
- Modify: `window.py`
- Modify: `README.md`
- Modify: `docs/操作手册.md`
- Modify: `docs/界面预览.png`
- Modify: `docs/界面预览-审核不通过.png`

**Interfaces:**
- Consumes: Task 1/2 的单按钮与阶段按钮

- [ ] 调整窗口、左侧栏、对话区、预览卡、底部输入框的间距与配色，表格正文字号至少 16px、默认行高至少 44px。
- [ ] 更新说明文字，删除“审核本阶段”“确认并进入下一步”等旧流程。
- [ ] 生成并目视检查正常预览及错误预览截图。
- [ ] 运行 `python -m unittest discover -s tests -v` 和启动器测试，确认全部通过。
- [ ] 提交最终改动。

