# 管束 Agent 工具路由 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让配置 API 后的管束对话由模型基于真实图形状态选择受控工具，而不是被本地关键词规则提前截获。

**Architecture:** 保留现有四类结构化动作作为工具注册表；调整入口路由，把布管字符图加入模型上下文，并统一用现有解析器校验模型指定的管孔。所有改变继续通过现有预览卡确认。

**Tech Stack:** Python 3、PyQt5、unittest、DeepSeek JSON 对话接口

**Spec:** `docs/superpowers/specs/2026-11-07-agent-tool-routing-design.md`

## Global Constraints

- 只修改 `DongLanpec-Agent-Demo`。
- 不覆盖工作区已有修改。
- 不让模型直接修改坐标或数据库。
- 未配置 API 时离线能力不回退。

## Review Focus

- 配置 API 后开放式删管请求必须进入模型而非本地规则。
- 确认/保留等控制命令仍应立即响应。
- 模型必须能看到真实布管字符图。
- 模型指定的行列号必须完整传入待确认方案。
- 模型没有动作时不得凭本地规则伪造方案。

---

### Task 1: Agent 路由与状态上下文

**Files:**
- Modify: `window.py`
- Modify: `ai_support/api_client.py`
- Test: `tests/test_agent_routing.py`

**Interfaces:**
- Produces: `is_immediate_local_control(text: str) -> bool`
- Produces: `layout_state["plan_view"] -> str`

- [ ] 先写并运行失败测试。
- [ ] 配置 API 时只让即时控制命令走本地，其它请求交给 DeepSeek。
- [ ] 将真实布管字符图加入经过清洗的模型上下文。
- [ ] 运行测试并确认通过。

### Task 2: 模型方案保持原始选择

**Files:**
- Modify: `window.py`
- Test: `tests/test_agent_routing.py`

**Interfaces:**
- Consumes: `parse_hole_ops(raw_items) -> (list[HoleOp], list[str])`
- Produces: 带 `tubes` 行列号的 `HoleOp` 待确认卡片

- [ ] 先写并运行失败测试。
- [ ] 使用统一解析器处理模型删管动作。
- [ ] 删除模型无动作时的本地固定方案兜底。
- [ ] 运行相关测试和完整测试套件。

