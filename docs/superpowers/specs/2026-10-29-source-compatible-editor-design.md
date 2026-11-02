# 管束 Demo 源程序兼容编辑器设计

## 目标

- 普通窗口启动，默认 1440×900，不再最大化。
- 使用 `Microsoft YaHei UI`，表格字号和行高接近正式 DongLanpec。
- 参数值列沿用正式程序的三种输入方式：普通表格编辑、只选下拉、可输入下拉。
- 编辑控件使用不透明白底和独立 delegate，消除旧文字与编辑框重影。
- 左栏改成 Codex 式项目导航：浅暖灰背景、紧凑分组、圆角选中项。

## 输入规则来源

规则只读参考正式项目：

- `modules/buguan/buguan_ziyong/My_Piping.py`
- `modules/buguan/buguan_ziyong/sheet_form_page.py`
- `modules/buguan/buguan_ziyong/tube_sheet_connection.py`
- `modules/buguan/buguan_ziyong/buguan_param_table_style.py`

Demo 内复制稳定的选项和编辑行为，不导入正式项目模块，不访问正式业务数据库，不修改正式项目。

## 编辑方式

- 只选下拉：管板类型、管程程数、管程分程形式、换热管布置方式、拉杆直径、管板连接方式、焊接结构形式。
- 可输入下拉：换热管外径 `do`、换热管公称长度 `LN`。
- 普通输入：其余允许人工修改的数值参数。
- 只读：上游数据和联动计算结果。

下拉框禁止滚轮误改。切换阶段前先清除旧单元格控件，避免控件叠加。所有三种编辑方式最终统一调用现有 `ReviewSession.apply_edit`，保留原来的联动、失效下游阶段、审核和入库逻辑。

## 验证

- 自动测试检查窗口尺寸、字体、编辑器类型、选项、可输入下拉、重绘后无重复控件、修改后数据进入审核会话。
- 运行完整测试并生成界面截图做视觉复核。
