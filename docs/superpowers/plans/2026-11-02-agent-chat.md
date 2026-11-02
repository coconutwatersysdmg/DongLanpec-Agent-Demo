# 管束 Agent 对话式交互 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让用户通过 DeepSeek 自然语言对话立即修改任意管束阶段草稿，并保留本地审核与入库闸门。

**Architecture:** `DeepSeekClient` 只产出经过白名单解析的回复与动作；`ReviewSession` 原子地应用跨阶段草稿修改并维护阶段失效关系；`DesignWindow` 负责异步调用、聊天展示和按需预览。无密钥时使用有限的本地解析器。

**Tech Stack:** Python 3、PyQt5、DeepSeek Chat Completions、urllib、unittest、SQLite

**Spec:** `docs/superpowers/specs/2026-11-02-agent-chat-design.md`

## Global Constraints

- 只修改独立 `DongLanpec-Agent-Demo`，正式 `DongLanpec` 保持不动。
- 模型不得直接写数据库、确认阶段或修改只读/联动字段。
- 后续阶段草稿立即修改，但审核顺序不得跳跃。
- API 网络请求必须在后台线程执行。
- 无 API Key 时不得冒充已调用模型。

## Review Focus

- 一个回复同时修改多个阶段时，所有合法动作都进入草稿且当前阶段不前跳。
- 修改已确认的早期阶段时，后续保存快照全部失效。
- 模型返回未知字段、只读字段、重复动作或非 JSON 时给出可理解错误，不破坏草稿。
- 用户连续快速发送时不启动重叠 API 请求。
- 对话历史和参数摘要必须限长，API Key 不得进入提示词、日志或聊天。

---

### Task 1: 结构化对话协议

**Files:**
- Modify: `ai_support/api_client.py`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Produces: `parse_chat_payload(raw) -> dict` 和 `DeepSeekClient.chat(history, context, current_stage, user_text) -> dict`

- [ ] 写失败测试：合法动作被规范化；未知阶段/字段与重复动作进入 `rejected`；请求中不包含 API Key。
- [ ] 运行目标测试并确认因接口不存在而失败。
- [ ] 实现白名单解析、限量历史/上下文和 DeepSeek JSON 请求。
- [ ] 运行 `python -m unittest tests.test_pipeline -v` 并确认通过。

### Task 2: 跨阶段草稿修改

**Files:**
- Modify: `review_session.py`
- Test: `tests/test_review_session.py`

**Interfaces:**
- Consumes: Task 1 的 `actions` 字段。
- Produces: `ReviewSession.apply_draft_actions(actions) -> dict`，返回 `applied` 与 `rejected`。

- [ ] 写失败测试：后续阶段立即修改且当前阶段不前跳；只读项拒绝；修改已确认阶段撤销下游快照并回退。
- [ ] 运行目标测试并确认失败原因是方法不存在。
- [ ] 实现批量校验、阶段失效、联动字段更新和逐项结果。
- [ ] 运行 `python -m unittest tests.test_review_session -v` 并确认通过。

### Task 3: 聊天为主的窗口与异步调用

**Files:**
- Modify: `window.py`
- Modify: `README.md`
- Modify: `docs/操作手册.md`
- Test: `tests/test_window.py`

**Interfaces:**
- Consumes: `DeepSeekClient.chat(...)`、`ReviewSession.apply_draft_actions(...)`。
- Produces: `DesignWindow.handle_chat_result(result)`、跨阶段本地解析、聊天式 UI。

- [ ] 写失败测试：开始设计后预览默认收起；本地指令可修改后续阶段；结构化结果显示变更/拒绝；请求运行期间禁止重复发送。
- [ ] 运行目标测试并确认失败。
- [ ] 重构发送链路为后台调用；增加对话标题、清空对话、新建对话/历史对话样式；修改后按需打开预览。
- [ ] 更新面向小白的操作手册和 API Key 说明。
- [ ] 运行 `python -m unittest tests.test_window -v` 并确认通过。

### Task 4: 全量验证

**Files:**
- Verify only

- [ ] 运行 `python -m unittest discover -s tests -v`。
- [ ] 运行 `python -m compileall -q .` 和 `git diff --check`。
- [ ] 运行截图模式并目视检查聊天主界面与按需预览。
- [ ] 确认正式 `DongLanpec` 的 `git status --short` 为空，Demo 的 drawio 备份文件未修改。
