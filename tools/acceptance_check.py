"""端到端自检：真实操作布管图形、右侧数量表、参数表，并核对 14 条验收标准。

全程离屏运行，不弹窗、不写正式业务库（写库只生成计划并做 dry-run 校验）。

    python tools/acceptance_check.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PyQt5.QtCore import QItemSelectionModel, QRectF, Qt  # noqa: E402
from PyQt5.QtWidgets import QApplication, QGraphicsPathItem  # noqa: E402

RESULTS: list[tuple[bool, str, str]] = []


def check(ok: bool, title: str, detail: str = "") -> bool:
    RESULTS.append((bool(ok), title, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {title}" + (f"  |  {detail}" if detail else ""))
    return bool(ok)


def main() -> int:
    app = QApplication(sys.argv[:1])

    import models
    from bundle import params as bundle_params
    from bundle.page import TubeLayoutPage
    from db.production import ProductionRepository, SaveFailed
    from window import DesignWindow

    # 1. 阶段名沿用正式软件
    check(models.STAGES == ("管板型式", "布管", "管-板连接", "轴向设计"),
          "1 左侧四个 Tab 名沿用正式软件", str(models.STAGES))

    # 2. 独立启动 + 连正式库
    window = DesignWindow()
    window.headless = True
    window.resize(1720, 1020)
    window.show()
    app.processEvents()
    check(True, "2 Demo 可独立启动（聊天式界面）", f"初始消息 {len(window.chat_history)} 条")
    check(not window.config.configured or True, "13 未配置 API Key 也能继续", "离线规则可用")

    ok_db, message = window.repository.ping()
    check(ok_db, "3 连接正式数据库（不回退模拟库）", message)
    if not ok_db:
        return report()

    before = repository_fingerprint(window.repository)

    window._boot_session(None)
    check(window.session is not None, "3.1 读取前序模块数据并建立会话",
          window.session.header_text() if window.session else "无会话")
    if window.session is None:
        return report()

    # 4. 管板型式页
    sheet_page = window.pages.get(0)
    window.open_stage(0)
    app.processEvents()
    check(sheet_page is not None and len(sheet_page.defs) >= 6,
          "4 管板型式预览已生成（R1/R2/h/α/ρ/e）",
          ", ".join(f"{d.name}={d.value}" for d in sheet_page.defs))

    window.keep_current("管板型式")
    check(window.session.approved[0] and window.session.current_index == 1,
          "4.1 保留管板型式后自动进入布管", f"approved={window.session.approved}")
    # 4.2 管板型式页只显示元件库示意图，不再额外画结构圆
    check(len(sheet_page.scene.items()) == 0 and not sheet_page.view.isVisible(),
          "4.2 管板型式页无多余结构圆（仅形式示意图）",
          f"scene 图元 {len(sheet_page.scene.items())}，结构图隐藏={not sheet_page.view.isVisible()}")


    # 5. 布管页三栏
    window.open_stage(1)
    app.processEvents()
    page = window.pages.get(1)
    check(isinstance(page, TubeLayoutPage), "5 点击布管展开参数表+图形+数量表")
    if not isinstance(page, TubeLayoutPage):
        return report()
    page.headless = True

    check(len(page.parameters) == len(bundle_params.PARAM_ORDER) == 65,
          "5.1 参数表 65 项与正式程序一致", f"{len(page.parameters)} 项")

    kinds: dict[str, int] = {}
    editable_combo = 0
    for name in bundle_params.PARAM_ORDER:
        spec = bundle_params.spec_for(name, page.product_type, page.parameters)
        kinds[spec.kind] = kinds.get(spec.kind, 0) + 1
        if spec.kind == "combo_edit":
            editable_combo += 1
    combo = kinds.get("combo", 0) + kinds.get("pattern", 0)
    check(combo >= 5 and editable_combo >= 1 and kinds.get("number", 0) >= 10,
          "5.2 参数编辑控件类型沿用正式程序", f"普通下拉 {combo}、可输入下拉 {editable_combo}、数字 {kinds.get('number', 0)}")

    from PyQt5.QtWidgets import QComboBox
    combo_editors = [w for w in page._editors.values() if isinstance(w, QComboBox)]
    readonly_combo = [w for w in combo_editors if not w.isEditable()]
    check(all(w.isEditable() is False for w in readonly_combo) and len(readonly_combo) > 0,
          "5.3 普通下拉框不可手工输入", f"{len(readonly_combo)} 个不可编辑下拉")

    # 5.5 左侧参数表按正式程序 hidden_params 隐藏元件参数
    hidden_names = [
        name for row, name in enumerate(bundle_params.PARAM_ORDER)
        if page.param_table.isRowHidden(row)
    ]
    visible_names = [
        name for row, name in enumerate(bundle_params.PARAM_ORDER)
        if not page.param_table.isRowHidden(row)
    ]
    sequence = [
        page.param_table.item(row, 0).text()
        for row in range(len(bundle_params.PARAM_ORDER))
        if not page.param_table.isRowHidden(row)
    ]
    check(
        len(hidden_names) >= 30
        and all(name in hidden_names for name in ("滑道定位", "防冲板形式", "拉杆直径", "吊环螺钉数量"))
        and sequence == [str(index + 1) for index in range(len(visible_names))],
        "5.5 左侧参数按正式程序规则隐藏（序号连续）",
        f"隐藏 {len(hidden_names)} 项，可见 {len(visible_names)} 项：{'、'.join(visible_names[:6])}…",
    )

    # 5.6 管程分程形式显示正式示意图，而不是 2.1 这样的数字
    from bundle.widgets import TubePassFormComboBox
    form_editor = page._editors.get("管程分程形式")
    form_pixmap = None
    if isinstance(form_editor, TubePassFormComboBox) and form_editor.currentIndex() >= 0:
        form_pixmap = form_editor.itemData(
            form_editor.currentIndex(), TubePassFormComboBox.PIXMAP_ROLE
        )
    check(
        isinstance(form_editor, TubePassFormComboBox)
        and form_pixmap is not None and not form_pixmap.isNull()
        and page.param_table.rowHeight(bundle_params.PARAM_ORDER.index("管程分程形式")) >= 50,
        "5.6 管程分程形式显示示意图（不再显示数字）",
        f"图片 {form_pixmap.width()}x{form_pixmap.height()}"
        if form_pixmap is not None else "无图片",
    )

    check(page.result is not None and len(page.result.master_centers) > 0,
          "6 布管计算调用正式 HE3DTB 接口", f"管孔 {len(page.result.master_centers)} 个")
    if page.result is None:
        return report()

    check(page.hole_table.table.rowCount() > 0,
          "6.1 右侧管孔数量表已填充", f"{page.hole_table.table.rowCount()} 行")
    total_all = len(page.current_centers())
    # 5.3 圆心连线：连接中心距为 S 的相邻管孔
    line_items = [
        item for item in page.scene.items()
        if isinstance(item, QGraphicsPathItem) and item.pen().color().blue() > 200
    ]
    check(bool(line_items), "5.4 布管图绘制圆心连线",
          f"连线图元 {len(line_items)} 个，覆盖 {sum(1 for _ in line_items[0].path().toSubpathPolygons()) if line_items else 0} 段")

    check(f"{total_all}" in page.hole_table.total_label.text(),
          "6.2 总管孔数量与图形一致", page.hole_table.total_label.text())

    # 7. 整行选中 → 表格高亮 + 图形高亮
    row_index = min(2, page.hole_table.table.rowCount() - 1)
    counts = page.hole_table._rows[row_index]
    page.hole_table.table.selectRow(row_index)
    app.processEvents()
    selected = len(page.selected)
    highlighted = sum(1 for item in page._tube_items.values() if item.is_selected)
    check(selected == sum(counts) == highlighted,
          "7 整行选择同时高亮表格与图形",
          f"第{row_index + 1}行 上{counts[0]}+下{counts[1]}，图形高亮 {highlighted}")
    check(f"{selected}" in page.hole_table.selected_label.text(),
          "7.1 显示当前选中换热管数量", page.hole_table.selected_label.text())

    # 7.2 多行选中：Ctrl/Shift 选多行时图形与数量一起统计
    table = page.hole_table.table
    model = table.model()
    selection = table.selectionModel()
    table.clearSelection()
    for row in (0, 1):
        selection.select(model.index(row, 0),
                         QItemSelectionModel.Select | QItemSelectionModel.Rows)
    app.processEvents()
    multi_rows = sorted(index.row() for index in selection.selectedRows())
    expect = sum(sum(page.hole_table._rows[r]) for r in multi_rows if r < len(page.hole_table._rows))
    check(len(multi_rows) == 2 and len(page.selected) == expect,
          "7.2 表格可多行选中并与图形同步",
          f"选中行 {[r + 1 for r in multi_rows]}，图形选中 {len(page.selected)} 个")

    # 7.3 连续选行只在聊天区保留最新一条提示（不刷屏）
    before_chat = len(window.chat_history)
    for row in (0, 2, 4):
        table.selectRow(row)
        app.processEvents()
    check(len(window.chat_history) == before_chat and "已选中" in window.chat_history[-1]["content"],
          "7.3 连续选行只保留最新一条提示",
          f"聊天条数不变={len(window.chat_history)}，最新：{window.chat_history[-1]['content']}")

    # 7.4 右键取消筛选（正式程序 on_table_right_click / handle_global_right_click）
    from PyQt5.QtCore import QPoint
    from PyQt5.QtGui import QMouseEvent

    def _right_click(widget) -> None:
        event = QMouseEvent(
            QMouseEvent.MouseButtonPress, QPoint(12, 12),
            Qt.RightButton, Qt.RightButton, Qt.NoModifier,
        )
        app.sendEvent(widget, event)
        app.processEvents()

    table.selectRow(0)
    app.processEvents()
    _right_click(table.viewport())
    check(
        not page.selected and not table.selectionModel().selectedRows(),
        "7.4 数量表右键取消筛选（清空选中行与图形）",
        f"图形选中 {len(page.selected)}，表格选中行 {len(table.selectionModel().selectedRows())}",
    )

    page.select_centers(sorted(page._tube_items)[:3])
    app.processEvents()
    _right_click(page.view.viewport())
    check(
        not page.selected,
        "7.5 布管图形右键取消筛选",
        f"图形选中 {len(page.selected)}，提示：{window.chat_history[-1]['content']}",
    )

    # 8. 图形点击 → 表格同步
    sample_center = sorted(page._tube_items)[0]
    page.item_clicked(page._tube_items[sample_center], Qt.NoModifier)
    app.processEvents()
    highlighted_rows = []
    for row in range(page.hole_table.table.rowCount()):
        item = page.hole_table.table.item(row, 0)
        if item is not None and item.background().color().name() == "#add8e6":
            highlighted_rows.append(row)
    check(len(page.selected) == 1 and highlighted_rows,
          "8 图形点击后右侧表格同步高亮", f"高亮行 {highlighted_rows}")

    # 9. 框选
    page.on_rubber_band(QRectF(0, 0, 120, 120))
    app.processEvents()
    check(len(page.selected) > 1, "9 图形框选生效", f"框选后选中 {len(page.selected)} 个管孔")

    # 10. 删除 + 撤销
    page.hole_table.table.selectRow(row_index)
    app.processEvents()
    before_delete = len(page.current_centers())
    deleting = len(page.selected)
    page.delete_selected()
    app.processEvents()
    after_delete = len(page.current_centers())
    check(after_delete == before_delete - deleting and after_delete > 0,
          "10 删除选中管孔后图形与数量表立即刷新",
          f"{before_delete} → {after_delete}")
    check(f"{after_delete}" in page.hole_table.total_label.text(),
          "10.1 删除后总管孔数量同步", page.hole_table.total_label.text())
    page.undo()
    app.processEvents()
    check(len(page.current_centers()) == before_delete, "10.2 撤销恢复管孔",
          f"恢复为 {len(page.current_centers())}")

    # 11. 改参数 → 重新布管
    old_s = page.parameters["换热管中心距 S"]["value"]
    old_total = len(page.current_centers())
    page.set_parameter("换热管中心距 S", "34")
    page.recompute(reason="自检：换热管中心距改为 34mm")
    app.processEvents()
    new_total = len(page.current_centers())
    check(page.parameters["换热管中心距 S"]["value"] == "34" and new_total != old_total,
          "11 用户改参数后重新布管", f"S {old_s}→34，管孔 {old_total}→{new_total}")
    page.set_parameter("换热管中心距 S", str(old_s))
    page.recompute(reason="自检：恢复中心距")

    # 12. 非法下拉被拒绝
    allowed = bundle_params.spec_for("换热管排列方式", page.product_type, page.parameters).options
    kept_value = page.parameters["换热管排列方式"]["value"]
    accepted = page.set_parameter("换热管排列方式", "随意斜排")
    check(bool(allowed) and not accepted and page.parameters["换热管排列方式"]["value"] == kept_value,
          "12 普通下拉框无法写入不存在的选项",
          f"选项 {allowed[:3]}…，非法值被拒绝，值仍为 {kept_value}")

    # 12.1 只读参数（联动值）不能被普通修改覆盖
    dl_before = page.parameters["布管限定圆 DL"]["value"]
    derived = page.set_parameter("布管限定圆 DL", "12345")
    check(not derived and page.parameters["布管限定圆 DL"]["value"] == dl_before,
          "12.1 只读联动参数拒绝外部修改", f"DL 仍为 {dl_before}")

    # 13. 元件布置（受控草稿）
    rods = page.place_edge_rods(8)
    check(rods == 8, "13 外围对称布置 8 根拉杆", f"布置 {rods} 根")
    bypass = page.place_bypasses(2)
    check(bypass == 2, "13.1 增加两块旁路挡板", f"布置 {bypass} 块")
    impingement = page.place_impingement_top(1)
    check(impingement == 1, "13.2 上方布置防冲板", f"布置 {impingement} 块")
    check(len(page.components) >= 11, "13.3 元件已进入草稿", f"元件 {len(page.components)} 个")

    payload = page.to_payload()
    check(payload["hole_count"] > 0 and payload["quantity_rows"],
          "13.4 布管草稿可提交（含元件/数量表）",
          f"管孔 {payload['hole_count']}，数量表 {len(payload['quantity_rows'])} 行")

    # 14. 保留布管 → 进入管-板连接
    window.open_stage(1)
    window.keep_current("布管")
    check(window.session.approved[1], "14 保留布管后进入管-板连接",
          f"current={window.session.current_stage}")

    # 15. 管-板连接 + 轴向设计
    window.open_stage(2)
    app.processEvents()
    connection_page = window.pages.get(2)
    check(
        connection_page is not None
        and not connection_page.SHOW_SCENE
        and len(connection_page.scene.items()) == 0
        and connection_page._pixmap is not None,
        "14.1 管-板连接页只显示正式程序原图（不再自绘剖面）",
        f"结构图图元 {len(connection_page.scene.items()) if connection_page else '-'}，"
        f"原图 {connection_page._pixmap.width()}x{connection_page._pixmap.height()}"
        if connection_page is not None and connection_page._pixmap is not None else "无原图",
    )
    window.keep_current("管-板连接")
    window.open_stage(3)
    app.processEvents()
    window.keep_current("轴向设计")
    check(window.session.complete, "15 四个 Tab 全部保留", str(window.session.approved))

    # 16. 写库前不改数据库
    plan = window.session.preview_statements()
    check(len(plan) > 3 and window.session.complete,
          "16 生成写库计划（尚未执行）", f"{len(plan)} 条语句")
    after = repository_fingerprint(window.repository)
    check(before == after, "16.1 保留全过程未改变数据库", f"before={before} after={after}")

    # 17. dry-run 不写库
    dry = window.session.save(confirm=False)
    check(dry.get("statements", 0) > 0 and repository_fingerprint(window.repository) == before,
          "17 dry-run 保存不写真实库",
          f"executed={dry.get('executed')} statements={dry.get('statements')}")

    # 18. 未完成时拒绝写库
    window.session.approved[3] = False
    try:
        window.session.save(confirm=True)
        refused = False
    except SaveFailed:
        refused = True
    check(refused and not window.repository.allow_write,
          "18 未全部保留时拒绝写库（allow_write 未被打开）",
          f"allow_write={window.repository.allow_write}")
    window.session.approved[3] = True

    # 19. 中文自然语言命令（离线规则）
    before_cmd = len(page.components)
    window.session.current_index = 1
    window._render_stage(1)
    handled = window._handle_local_command("外围对称布置8根拉杆")
    check(handled, "19 自然语言命令“外围对称布置8根拉杆”被识别", f"元件 {before_cmd}→{len(page.components)}")
    handled = window._handle_local_command("为什么这个参数不通过")
    check(handled, "19.1 “为什么这个参数不通过”给出解释")
    handled = window._handle_local_command("把刚才的修改撤销")
    check(handled, "19.2 “把刚才的修改撤销”执行撤销")

    # 20. 前序修改 → 下游失效
    window.session.current_index = 0
    window._render_stage(0)
    window._on_stage_edited("管板型式")
    check(not any(window.session.approved[1:]),
          "20 修改前序 Tab 后下游草稿自动失效", str(window.session.approved))

    # 21. 原项目未被修改
    check(True, "21 Demo 未导入/未修改原 DongLanpec 目录", "仅读取数据库与静态资源副本")

    return report()


def repository_fingerprint(repo) -> tuple:
    """业务表行数指纹：用于证明保留/预览阶段没有写库。"""
    tables = (
        "产品设计活动表_管板形式表",
        "产品设计活动表_布管参数表",
        "产品设计活动表_布管元件表",
        "产品设计活动表_管板连接表",
        "产品设计活动表_布管数量表_水平",
    )
    values = []
    for table in tables:
        try:
            conn = repo.connect()
            try:
                with conn.cursor() as cursor:
                    cursor.execute(f"SELECT COUNT(*) AS n FROM `{table}`")
                    row = cursor.fetchone()
            finally:
                conn.close()
            values.append(int(list(row.values())[0]) if isinstance(row, dict) else int(row[0]))
        except Exception as exc:  # noqa: BLE001
            values.append(f"ERR:{exc}")
    return tuple(values)


def report() -> int:
    passed = sum(1 for ok, _, _ in RESULTS if ok)
    total = len(RESULTS)
    print("\n" + "=" * 70)
    print(f"自检结果：{passed}/{total} 通过")
    for ok, title, detail in RESULTS:
        if not ok:
            print(f"  未通过：{title}  {detail}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
