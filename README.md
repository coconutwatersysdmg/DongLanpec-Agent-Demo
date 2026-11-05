# 管束设计 Agent Demo

独立的管束设计演示程序：把正式软件 `DongLanpec` 的管束设计能力（65 项布管参数表、正式布管计算组件 `HE3DTB.dll`、
管孔坐标/元件/数量表、真实数据库读写）抽取到本目录内，用聊天界面驱动四个正式 Tab：

`管板型式 → 布管 → 管-板连接 → 轴向设计`

- **不导入**正式项目目录，不修改 `DongLanpec` 与 `DongLanpec - AI` 任何文件；需要的代码是**复制/重构**到本目录 `bundle/`。
- 连接**正式数据库**（`产品设计活动库` / `元件库` / `配置库`），不建立模拟 SQLite 业务库。
- 布管图形与右侧管孔数量表是**真实交互**：整行/多行选择、框选、点击、删除、撤销、元件布置都会同时更新图形、表格与写库数据。
- 图形含正式程序同款**圆心连线**（按中心距 S 连接相邻管孔）；操作反馈只保留最新一条，不会刷屏。
- 左侧参数完全按正式程序规则**隐藏元件参数**（滑道/防冲板/中间挡板/吊环螺钉/拉杆/折流板…），
  改在“布置元件”时弹窗确认；管程分程形式直接**显示分程示意图**；图形/数量表**右键取消筛选**。

## 快速开始

```bash
python -m pip install -r requirements.txt
python main.py
```

或双击 `启动管束设计助手.cmd`。

启动后点左侧 **开始管束设计**：程序会读取正式库中前序模块已保存的数据，按四个 Tab 生成草稿；
每个 Tab 预览底部只有一个 **保留** 按钮；四个 Tab 全部保留后才会写库。

## 目录

| 路径 | 说明 |
| --- | --- |
| `main.py` | 入口（`--screenshot` 支持离屏截图，用于验收留证） |
| `window.py` | 聊天式主窗口、左侧四 Tab 导航、预览卡片、保留/写库流程 |
| `session.py` | 四阶段状态机：保留顺序、下游失效、单事务写库 |
| `models.py` | 四个正式 Tab 名称 |
| `bundle/page.py` | 布管页：参数表 + 布管图形 + 右侧管孔数量表 + 元件操作 |
| `bundle/engine.py` | 调用正式 `HE3DTB.dll` 计算布管，生成管孔坐标与关键尺寸 |
| `bundle/params.py` | 正式程序 65 项布管参数、控件类型与选项、联动映射 |
| `bundle/items.py` / `view.py` | 图元（换热管/拉杆/挡板/滑道…）与视图（缩放、框选、平移） |
| `bundle/hole_table.py` | 右侧“管孔数量分布”表（按行/按列、整行/多行选中、淡蓝高亮、右键取消筛选） |
| `bundle/widgets.py` | 分程形式示意图下拉框、元件参数确认弹窗（对标正式程序同名控件） |
| `bundle/stages.py` | 管板型式、管-板连接、轴向设计三个预览页 |
| `bundle/dll/` | `HE3DTB.dll`、`Newtonsoft.Json.dll`（正式程序自带组件副本） |
| `bundle/static/` | 正式程序示意图副本（分程形式、元件按钮、焊缝、管板形式等） |
| `db/production.py` | 正式数据库只读查询 + 单事务写库计划 |
| `ai_support/` | DeepSeek 客户端与结构化输出校验 |
| `tools/acceptance_check.py` | 40 项端到端自检（真实操作图形/表格，不写库） |
| `tests/` | 单元测试 + 端到端自检用例 |
| `docs/交付说明.md` | 交付清单、运行/配置/演示步骤、已验证与未验证项、数据库排错 |
| `legacy_demo/legacy_modules/` | 早期演示版本模块（已不被新实现引用，仅存档） |

## 数据库配置

默认按正式程序一致的方式连接：`localhost:3306`，用户 `root`，密码 `123456`，库 `产品设计活动库`。
可用环境变量覆盖（`db/production.py`）：

```
DONGLANPEC_DB_HOST / DONGLANPEC_DB_PORT / DONGLANPEC_DB_USER
DONGLANPEC_DB_PASSWORD / DONGLANPEC_DB_NAME
```

连接失败时界面会直接报错并给出排查步骤，**不会**回退到模拟数据库。

## 验证

```bash
python -m unittest discover -s tests -q          # 24 项（含端到端）
python tools/acceptance_check.py                 # 40 项自检明细
python main.py --screenshot artifacts/stage1.png --stage 1   # 离屏截图
```

详细说明见 [docs/交付说明.md](docs/交付说明.md)，早期版本的操作手册见 [docs/操作手册.md](docs/操作手册.md)。
