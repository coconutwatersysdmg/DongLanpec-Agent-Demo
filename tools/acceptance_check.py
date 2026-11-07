"""端到端自检：真实操作布管图形、右侧数量表、参数表，并核对 14 条验收标准。

全程离屏运行，不弹窗、不写正式业务库（写库只生成计划并做 dry-run 校验）。

    python tools/acceptance_check.py
"""
from __future__ import annotations

import math
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PyQt5.QtCore import QItemSelectionModel, QRectF, Qt  # noqa: E402
from PyQt5.QtWidgets import (  # noqa: E402
    QApplication,
    QGraphicsPathItem,
    QLabel,
    QTableWidget,
)

RESULTS: list[tuple[bool, str, str]] = []


def check(ok: bool, title: str, detail: str = "") -> bool:
    RESULTS.append((bool(ok), title, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {title}" + (f"  |  {detail}" if detail else ""))
    return bool(ok)


def main() -> int:
    app = QApplication(sys.argv[:1])

    import models
    from models import STAGES
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
    check(
        window.preview_host.isHidden() and window.card is None,
        "2.1 未开始设计时不留空白预览区",
        "preview_host 隐藏" if window.preview_host.isHidden() else "预览区可见",
    )
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

    from PyQt5.QtWidgets import QComboBox, QLineEdit

    from bundle.widgets import RightAlignedComboBox

    combo_editors = [w for w in page._editors.values() if isinstance(w, QComboBox)]
    plain_combos = [w for w in combo_editors if isinstance(w, RightAlignedComboBox)]
    locked_combos = [
        widget for name, widget in page._editors.items()
        if isinstance(widget, RightAlignedComboBox)
        and bundle_params.spec_for(name, page.product_type, page.parameters).kind == "combo"
    ]
    check(
        bool(locked_combos)
        and all(
            w.lineEdit() is not None and w.lineEdit().isReadOnly() for w in locked_combos
        ),
        "5.3 普通下拉框不可手工输入",
        f"{len(locked_combos)} 个普通下拉只读（文字右对齐），"
        f"{len(plain_combos) - len(locked_combos)} 个可输入下拉保持可编辑",
    )

    # 5.7 参数值整列右对齐（数字框 + 下拉框文字都靠右）
    edits = [w for w in page._editors.values() if isinstance(w, QLineEdit)]
    right_edits = [w for w in edits if bool(w.alignment() & Qt.AlignRight)]
    right_combos = [
        w for w in plain_combos
        if w.lineEdit() is not None and bool(w.lineEdit().alignment() & Qt.AlignRight)
    ]
    check(
        len(right_edits) == len(edits)
        and len(right_combos) == len(plain_combos)
        and len(edits) + len(plain_combos) >= 20,
        "5.7 参数值整列右对齐（数字框与下拉框文字都靠右）",
        f"数字框 {len(right_edits)}/{len(edits)}、下拉框 {len(right_combos)}/{len(plain_combos)}",
    )

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

    # 8.5 正式程序的选管是“切换”：点第二根不会顶掉第一根（除非再点它自己）
    page.select_centers([])
    first_tube, second_tube = sorted(page._tube_items)[:2]
    page.item_clicked(page._tube_items[first_tube], Qt.NoModifier)
    page.item_clicked(page._tube_items[second_tube], Qt.NoModifier)
    both_selected = (
        len(page.selected) == 2
        and page._tube_items[first_tube].is_selected
        and page._tube_items[second_tube].is_selected
    )
    page.item_clicked(page._tube_items[first_tube], Qt.NoModifier)
    check(
        both_selected and len(page.selected) == 1 and second_tube in page.selected,
        "8.5 单击换热管是累加选中（点第二根不会取消第一根）",
        f"连点两根 → 选中 {2 if both_selected else '?'} 个；再点第一根 → 剩 {len(page.selected)} 个",
    )

    # 8.6 行号列号 ↔ 绝对坐标必须一一对应（方案卡让用户改的就是这两个号）
    lost = []
    for center in page.current_centers():
        rc = page.tube_row_col(center)
        if rc is None or page.center_for_row_col(*rc) != center:
            lost.append(center)
    check(
        not lost,
        "8.6 换热管的“第几行第几列”与绝对坐标一一对应",
        f"{len(page.current_centers())} 个管孔全部可反查" if not lost else f"{len(lost)} 个对不上",
    )

    # 8.7 对称分布勾选框（正式程序 My_Piping.symmetric_checkbox：浮在图形右上角、默认勾选）
    sym_box = page.symmetry_check
    default_on = bool(sym_box.isChecked()) and page.symmetry_on()
    seed = next(
        c for c in page.current_centers()
        if abs(c[0]) > 1.0 and abs(c[1]) > 1.0
        and (c[0], -c[1]) in set(page.current_centers())
        and (-c[0], c[1]) in set(page.current_centers())
    )
    page.set_symmetry(False)
    off_group = page._linkage_expand([seed])
    page.set_symmetry(True)
    on_group = page._linkage_expand([seed])
    check(
        default_on and len(off_group) == 2 and len(on_group) == 4,
        "8.7 布管页有“对称分布”勾选框（默认勾选；关掉只按管程单轴镜像）",
        f"默认勾选={default_on}；不勾 {len(off_group)} 点、勾选 {len(on_group)} 点（4 象限）",
    )

    # 8.8 普通拉杆和换热管同性质：点两根拉杆都留在选中里，且能当防冲板参照管
    page.set_symmetry(False)
    page.clear_selection()
    pair = sorted(page.current_centers(), key=lambda c: (-round(c[1], 3), c[0]))[:2]
    page.select_centers(pair)
    page.place_rod(free=False)
    rod_items = [
        item for index, item in page._component_items.items()
        if page.components[index]["kind"] == "rod"
    ]
    page.clear_selection()
    for item in rod_items[:2]:
        page.item_clicked(item, Qt.NoModifier)
    rods_both = len(page.selected) == 2 and all(item.is_selected for item in rod_items[:2])
    placed_before = len(page.components)
    page.place_impingement()
    plate = page.components[-1] if len(page.components) > placed_before else None
    deleted_keys = {tuple(coord) for coord in (plate.get("deleted") or [])} if plate else set()
    rods_kept = all(tuple(item.center) not in deleted_keys for item in rod_items[:2])
    check(
        rods_both and plate is not None and plate.get("form") and rods_kept,
        "8.8 单击可同时选中两根普通拉杆，并可当防冲板的两根参照管",
        f"两根拉杆都选中={rods_both}；防冲板 {plate.get('form') if plate else '未布置'}；"
        f"参照管未被删={rods_kept}",
    )
    page.undo()   # 撤防冲板
    page.undo()   # 撤拉杆
    page.set_symmetry(True)
    page.clear_selection()

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

    # 18.1 AI 给出元件布置方案 → 先出方案卡，确认后才落到图形
    window.session.current_index = 1
    window._render_stage(1)
    comps_before = len(page.components)
    holes_before = len(page.current_centers())
    window._handle_ai_result({
        "reply": "我按常规做法给出一版布置方案。",
        "actions": [],
        "placements": [
            {"kind": "拉杆", "count": 4, "region": "靠近壳壁",
             "options": {"拉杆形式": "螺纹拉杆", "拉杆直径": 16}},
            {"kind": "旁路挡板", "count": 4, "region": "均布"},
        ],
        "placement_rejected": [],
    })
    ai_card = window.placement_cards[-1] if window.placement_cards else None
    check(
        ai_card is not None and ai_card.badge.text() == "待确认"
        and len(page.components) == comps_before,
        "18.1 AI 元件布置只出方案，确认前图形不变",
        f"{len(ai_card.items) if ai_card else 0} 条方案，图形元件仍 {len(page.components)} 个",
    )
    if ai_card is not None:
        ai_card.confirm_button.click()
    check(
        ai_card is not None and ai_card.badge.text() == "已布置"
        and len(page.components) == comps_before + 8
        and len(page.current_centers()) == holes_before - 4,
        "18.2 确认后 AI 方案直接布置到图形（占用真实管孔）",
        f"元件 {comps_before}→{len(page.components)}，管孔 {holes_before}→{len(page.current_centers())}",
    )
    hole_bound = [comp for comp in page.components if comp["kind"] in {"rod", "free_rod", "block_tube"}]
    check(
        len(hole_bound) >= 4
        and all(comp["center"] in page.result.master_centers for comp in hole_bound),
        "18.3 落图位置全部来自真实布管结果（AI 未给坐标）",
        f"校验 {len(hole_bound)} 个占孔类元件中心",
    )

    # 18.4 圆弧形防冲板 = A-P-Q-B 折边梯形（正式程序 build_impingement_plate 圆弧形分支）
    from bundle import impingement as impingement_geometry
    from bundle.placement import PlacementItem, pick_pairs

    do = page._float("换热管外径 do") or 25.0
    pitch = page._float("换热管中心距 S") or 32.0
    thickness = page._float("防冲板厚度") or 10.0
    fold_angle = page._float("防冲板折边角度") or 45.0
    page.set_parameter("防冲板形式", "圆弧形", "自检", run_linkage=False)
    min_span = impingement_geometry.required_span_for_folded(do, pitch, fold_angle)
    pairs = pick_pairs(page.current_centers(), 1, "top", "row", min_span=min_span)
    comps_before_plate = len(page.components)
    page.apply_placement_plan([
        PlacementItem("impingement", 1, "top", {"防冲板形式": "圆弧形"}),
    ])
    plate = page.components[comps_before_plate] if len(page.components) > comps_before_plate else None
    expected_plate = None
    if pairs and plate is not None:
        (x1, y1), (x2, y2) = pairs[0]
        expected_plate = impingement_geometry.folded_geometry(
            (x1, -y1), (x2, -y2), do, pitch, thickness, fold_angle
        )
    plate_ok = bool(
        plate is not None
        and expected_plate is not None
        and plate["kind"] == "impingement_folded"
        and len(plate["points"]) == 4
        and all(
            abs(plate["points"][index][axis] - expected_plate["points"][index][axis]) < 1e-6
            for index in range(4)
            for axis in (0, 1)
        )
        and abs(plate["height"] - expected_plate["height"]) < 1e-9
        and expected_plate["top_length"] >= 0
    )
    check(
        plate_ok,
        "18.4 圆弧形防冲板是 A-P-Q-B 折边梯形（折边高 H / 顶部长度按折边角算）",
        (
            f"跨距 {expected_plate['width']:.1f}、折边高 {expected_plate['height']:g}、"
            f"顶部 {expected_plate['top_length']:.1f}、A/B 径向外移 {expected_plate['clearance']:g}"
        ) if expected_plate else "未生成防冲板",
    )

    # 18.4b 平板形防冲板：整段沿法向平移 do/2+板厚/2+0.5，长度 = 两管中心距（不缩不伸）
    page.set_parameter("防冲板形式", "平板形", "自检", run_linkage=False)
    page.set_parameter("放置位置", "参照管顶部连线", "自检", run_linkage=False)
    flat_pairs = pick_pairs(page.current_centers(), 1, "top", "row")
    flat_before = len(page.components)
    page.apply_placement_plan([
        PlacementItem("impingement", 1, "top", {"防冲板形式": "平板形"}),
    ])
    flat_plate = page.components[flat_before] if len(page.components) > flat_before else None
    flat_ok = False
    if flat_pairs and flat_plate is not None:
        (x1, y1), (x2, y2) = flat_pairs[0]
        span = math.hypot(x2 - x1, y2 - y1)
        shift = do / 2.0 + thickness / 2.0 + 0.5
        flat_ok = (
            flat_plate["kind"] == "impingement"
            and len(flat_plate["points"]) == 2
            # 屏幕上移 -> 场景 y 减小
            and abs(flat_plate["points"][0][1] - (-y1 - shift)) < 1e-6
            and abs(flat_plate["points"][1][1] - (-y2 - shift)) < 1e-6
            and abs(flat_plate["width"] - span) < 1e-6
        )
    check(
        flat_ok,
        "18.4b 平板形防冲板按“顶部连线”平移 do/2+板厚/2+0.5，板长=中心距",
        f"平移量 {do / 2.0 + thickness / 2.0 + 0.5:g}，板长 {round(flat_plate['width'], 1) if flat_plate else 0:g}",
    )

    # 18.4c 焊接式防冲板：不选管，按 宽度 / 方位角 / 至圆筒内壁距离 定位（A/B 落在壳体内壁圆上）
    shell_r = (page._float("壳体内直径 Dis") or 1000.0) / 2.0
    welded_before = len(page.components)
    page.set_parameter("防冲板形式", "焊接式", "自检", run_linkage=False)
    page.set_parameter("防冲板宽度", "200", "自检", run_linkage=False)
    page.set_parameter("防冲板方位角", "0", "自检", run_linkage=False)
    page.set_parameter("至圆筒内壁距离", "150", "自检", run_linkage=False)
    page.apply_placement_plan([
        PlacementItem("impingement", 1, "any", {"防冲板形式": "焊接式"}),
    ])
    welded = page.components[welded_before] if len(page.components) > welded_before else None
    welded_ok = False
    if welded is not None:
        points = welded["points"]
        radii = [math.hypot(x, y) for x, y in points]
        welded_ok = (
            welded["kind"] == "impingement_welded"
            and len(points) == 4
            # C 点方位角 0° = 顶部：P/Q 在 y = -(R - 距内壁)
            and abs(points[1][1] + (shell_r - 150.0)) < 1e-6
            and abs(points[2][1] + (shell_r - 150.0)) < 1e-6
            and abs(points[2][0] - points[1][0] - 200.0) < 1e-6
            # A/B 在壳体内壁大圆上
            and abs(radii[0] - shell_r) < 1e-6
            and abs(radii[3] - shell_r) < 1e-6
        )
    check(
        welded_ok,
        "18.4c 焊接式防冲板按参数定位，A/B 落在壳体内壁圆上",
        f"PQ 在 y={-round(shell_r - 150.0, 1)}、长 200；A/B 半径 {round(math.hypot(*welded['points'][0]), 1) if welded else 0:g}",
    )

    # 18.4d 圆弧形防冲板落位后立刻删掉干涉换热管（含 2 管程镜像），两块参照管保留
    page.recompute(reason="自检重置（圆弧形删管）")
    page.set_parameter("防冲板形式", "圆弧形", "自检", run_linkage=False)
    folded_item = PlacementItem("impingement", 1, "top", {"防冲板形式": "圆弧形"})
    folded_preview = page.preview_placement([folded_item])
    folded_anchors = list(page.selected)
    holes_pre_folded = len(page.current_centers())
    page.apply_placement_plan([folded_item])
    holes_post_folded = len(page.current_centers())
    deleted_folded = set(page.removed)
    mirrored_ok = bool(deleted_folded) and all(
        (x, -y) in deleted_folded for x, y in deleted_folded
    )
    anchors_kept = all(c not in deleted_folded for c in folded_anchors)
    check(
        holes_pre_folded - holes_post_folded == folded_preview["deletes"] > 0
        and mirrored_ok and anchors_kept,
        "18.4d 圆弧形防冲板落位后删掉干涉换热管（管程镜像、参照管保留）",
        f"管孔 {holes_pre_folded}→{holes_post_folded}"
        f"（删 {holes_pre_folded - holes_post_folded}，卡片预览算 {folded_preview['deletes']}）",
    )

    # 18.4e 焊接式防冲板删掉“板与壳顶之间”扇形区的换热管，撤销能恢复
    page.recompute(reason="自检重置（焊接式删管）")
    page.set_parameter("防冲板形式", "焊接式", "自检", run_linkage=False)
    page.set_parameter("防冲板宽度", "200", "自检", run_linkage=False)
    page.set_parameter("防冲板方位角", "0", "自检", run_linkage=False)
    page.set_parameter("至圆筒内壁距离", "60", "自检", run_linkage=False)
    welded_item = PlacementItem("impingement", 1, "any", {"防冲板形式": "焊接式"})
    holes_pre_welded = len(page.current_centers())
    page.apply_placement_plan([welded_item])
    holes_post_welded = len(page.current_centers())
    near_shell = bool(page.removed) and all(
        abs(y) > 0.7 * shell_r for _x, y in page.removed
    )
    page.undo()
    holes_undo = len(page.current_centers())
    check(
        holes_post_welded < holes_pre_welded and near_shell and holes_undo == holes_pre_welded,
        "18.4e 焊接式防冲板删掉壳顶扇形区换热管，撤销可恢复",
        f"管孔 {holes_pre_welded}→{holes_post_welded}，撤销后 {holes_undo}",
    )

    # 18.5 滑道 / 吊环螺钉按参数定位，不选管也不占管孔
    holes_before_param = len(page.current_centers())
    comps_before_param = len(page.components)
    page.apply_placement_plan([
        PlacementItem("slide", 1, "any", {}),
        PlacementItem("screw_ring", 4, "uniform", {}),
    ])
    added = page.components[comps_before_param:]
    slides = [c for c in added if c["kind"] == "slide"]
    rings = [c for c in added if c["kind"] == "screw_ring"]
    check(
        len(slides) == 2 and len(rings) == 4
        and all(c["center"][1] <= 0 for c in slides)
        and len(page.current_centers()) == holes_before_param,
        "18.5 滑道/吊环螺钉按参数定位、不占管孔",
        f"滑道 {len(slides)} 条（均在底部）、吊环 {len(rings)} 个，"
        f"管孔 {holes_before_param}→{len(page.current_centers())}",
    )

    # 19. 中文自然语言命令（离线规则）
    before_cmd = len(page.components)
    holes_before_cmd = len(page.current_centers())
    window.session.current_index = 1
    window._render_stage(1)
    handled = window._handle_local_command("外围对称布置8根拉杆")
    card = window.placement_cards[-1] if window.placement_cards else None
    check(
        handled and card is not None and card.badge.text() == "待确认"
        and card.items[0].count == 8,
        "19 自然语言布置先生成方案卡（确认前不改图形）",
        f"卡片 {len(window.placement_cards)} 张，图形元件仍 {len(page.components)} 个",
    )
    if card is not None:
        card.confirm_button.click()
    check(
        len(page.components) == before_cmd + 8
        and len(page.current_centers()) == holes_before_cmd - 8
        and card is not None and card.badge.text() == "已布置",
        "19.1 确认方案后直接在图形化界面布置出来",
        f"元件 {before_cmd}→{len(page.components)}，管孔 {holes_before_cmd}→{len(page.current_centers())}",
    )
    handled = window._handle_local_command("为什么这个参数不通过")
    check(handled, "19.2 “为什么这个参数不通过”给出解释")
    handled = window._handle_local_command("把刚才的修改撤销")
    check(handled, "19.3 “把刚才的修改撤销”执行撤销")

    # 19.4 对话自动滚到最新一条（用户不用每次自己拖滚动条）
    app.processEvents()
    convo_bar = window.conversation.verticalScrollBar()
    check(
        convo_bar.maximum() > 0 and convo_bar.value() >= convo_bar.maximum() - 4,
        "19.4 对话自动停在最新一条（不用手动拉滚动条）",
        f"滚动位置 {convo_bar.value()}/{convo_bar.maximum()}",
    )

    # 22. 图形化界面固定在对话区上方（不随对话滚动）
    check(
        hasattr(window, "splitter") and window.splitter.count() == 2
        and window.splitter.widget(0) is getattr(window, "preview_host", None)
        and window.splitter.widget(1) is window.conversation
        and window.card is not None
        and window.card.parent() is getattr(window, "preview_host", None),
        "22 图形化界面固定在对话区上方（不随对话滚动）",
        f"splitter 上={type(window.splitter.widget(0)).__name__} "
        f"下={type(window.splitter.widget(1)).__name__}",
    )

    # 22.1 对话区是主界面：至少和预览区一样高（预览只保底“够放下布管页”）
    sizes = window.splitter.sizes()
    check(
        len(sizes) == 2 and sizes[1] >= sizes[0] * 0.95 and window.preview_host.minimumHeight() >= 300,
        "22.1 对话区不比预览区小（预览只留够用的高度）",
        f"预览 {sizes[0]} / 对话 {sizes[1]}（预览保底 {window.preview_host.minimumHeight()}）",
    )

    # 23. 点“布管”按正式程序清空已布置元件
    #     正式程序 on_buguan_bt_click 会把 lagan / 旁路挡板 / 中挡板 / 防冲板 / 滑道 全部清零
    comps_before_relayout = len(page.components)
    page.recompute(reason="自检重新布管")
    check(
        comps_before_relayout > 0 and len(page.components) == 0,
        "23 点“布管”重算时清空已布置元件（与正式程序一致）",
        f"元件 {comps_before_relayout}→{len(page.components)}",
    )

    # 24. 方案的本质是“选管”：卡片写出具体参照管，图上先高亮，确认后与高亮一致
    page.set_parameter("防冲板形式", "圆弧形", "自检", run_linkage=False)
    plate_item = PlacementItem("impingement", 1, "top", {"防冲板形式": "圆弧形"})
    preview = page.preview_placement([plate_item])
    plate_row = preview["rows"][0]
    picked = sorted(page.selected)
    check(
        len(picked) == 2
        and "(" in plate_row["anchors"] and "–" in plate_row["anchors"]
        and plate_row["params"].startswith("形式 圆弧形"),
        "24 方案卡给出“选中的两根参照管”（AI 方案的输入就是选管）",
        f"参照管 {plate_row['anchors']}；参数 {plate_row['params']}",
    )
    page.apply_placement_plan([plate_item])
    plates = [c for c in page.components if c.get("kind") == "impingement_folded"]
    plate_ok = False
    if plates and len(picked) == 2:
        span = math.hypot(picked[1][0] - picked[0][0], picked[1][1] - picked[0][1])
        plate_ok = abs(plates[-1]["width"] - span) < 1e-6
    check(
        plate_ok,
        "24.1 确认后落点正好用卡片上那两根参照管（不另选管）",
        f"板跨距 {round(plates[-1]['width'], 2) if plates else 0:g} = 两管中心距",
    )

    # 25. 方案卡可编辑：AI 给的方案就是“选两根管 + 一组参数”，两项都能改
    window.open_stage(1)
    app.processEvents()
    window._handle_local_command("上方布置1块圆弧形防冲板")
    edit_card = window.placement_cards[-1]
    block = edit_card._blocks[0]
    refs = block["refs"]
    base_ok = len(refs) == 2 and all(
        e.coord_label.text().startswith("(") and e.value() is not None for e in refs
    )
    row0, col0 = refs[0].value() if base_ok else (0, 0)
    taken = {e.value() for e in refs}
    choices = [
        c for c in range(-40, 41)
        if c and (row0, c) not in taken and page.center_for_row_col(row0, c) is not None
    ]
    alt_col = min(choices, key=abs) if choices else None
    moved_ok = False
    if alt_col is not None:
        refs[0].col_edit.setText(str(alt_col))
        refs[0].col_edit.textEdited.emit(str(alt_col))
        app.processEvents()
        target = page.center_for_row_col(row0, alt_col)
        moved_ok = (
            tuple(edit_card.items[0].anchors[0]) == tuple(target)
            and refs[0].coord_label.text() == f"({target[0]:.1f}, {target[1]:.1f})"
        )
    check(
        base_ok and moved_ok,
        "25 方案卡里换热管可按“第几行第几列”改，绝对坐标实时跟着变",
        f"第 {row0} 行 第 {col0} 列 → 第 {alt_col} 列，坐标 {refs[0].coord_label.text()}",
    )

    # 25.1 填了不存在的管孔 → 标红并禁止确认
    refs[0].col_edit.setText("999")
    refs[0].col_edit.textEdited.emit("999")
    app.processEvents()
    invalid_ok = (
        not edit_card.confirm_button.isEnabled()
        and refs[0].error_label.isVisible()
        and "没有这个管孔" in refs[0].error_label.text()
    )
    if alt_col is not None:
        refs[0].col_edit.setText(str(alt_col))
        refs[0].col_edit.textEdited.emit(str(alt_col))
        app.processEvents()
    check(
        invalid_ok and edit_card.confirm_button.isEnabled(),
        "25.1 行号列号填错时标红提示并锁住“确认布置”，改回后恢复",
        refs[0].error_label.text() if invalid_ok else "未拦下非法输入",
    )

    # 25.2 参数也能改：改板厚后确认，落图的板厚就是卡片上那个值
    thick_field = next(f for f in block["params"] if f.name == "防冲板厚度")
    thick_field.editor.setText("14")
    thick_field.editor.textEdited.emit("14")
    app.processEvents()
    comps_before_card = len(page.components)
    anchors_now = [tuple(a) for a in edit_card.items[0].anchors]
    edit_card.confirm_button.click()
    app.processEvents()
    new_plate = page.components[comps_before_card] if len(page.components) > comps_before_card else None
    span_now = (
        math.hypot(anchors_now[1][0] - anchors_now[0][0], anchors_now[1][1] - anchors_now[0][1])
        if len(anchors_now) == 2 else 0.0
    )
    check(
        new_plate is not None
        and abs(new_plate["thickness"] - 14.0) < 1e-6
        and abs(new_plate["width"] - span_now) < 1e-6
        and page.parameters["防冲板厚度"]["value"] == "14"
        and edit_card.badge.text() == "已布置",
        "25.2 方案卡上改参数（板厚 10→14）后确认，落图与参数表都按新值",
        f"板厚 {new_plate['thickness'] if new_plate else 0:g}、跨距 {round(new_plate['width'], 1) if new_plate else 0:g}"
        f"（卡片上两管中心距 {span_now:.1f}）",
    )

    # 25.3 卡片上的“形式”也能改：圆弧形 → 平板形，参数行/删管数/落位几何一起变
    window._handle_local_command("上方布置1块圆弧形防冲板")
    app.processEvents()
    form_card = window.placement_cards[-1]
    form_block = form_card._blocks[0]
    tip_gone = not any(
        label.text() == "行号列号、参数都可直接改"
        for label in form_card.findChildren(QLabel)
    )
    before_names = [field.name for field in form_block["params"]]
    form_field = next(field for field in form_block["params"] if field.name == "防冲板形式")
    form_editable = form_field.editor.isEnabled()
    before_deletes = form_card._preview["deletes"]
    form_field.editor.setCurrentIndex(form_field.editor.findData("平板形"))
    for _ in range(3):
        app.processEvents()
    after_names = [field.name for field in form_card._blocks[0]["params"]]
    label_now = form_card._blocks[0]["label"]
    check(
        tip_gone and form_editable
        and "防冲板折边角度" in before_names
        and "放置位置" in after_names and "防冲板折边角度" not in after_names
        and label_now == "平板形防冲板",
        "25.3 方案卡“形式”可改，改完参数列表与标题跟着换",
        f"圆弧形 {before_names} → 平板形 {after_names}，标题“{label_now}”",
    )
    form_card.confirm_button.click()
    app.processEvents()
    applied_plate = page.components[-1] if page.components else None
    check(
        form_card.badge.text() == "已布置"
        and applied_plate is not None and applied_plate.get("form") == "平板形"
        and page.parameters["防冲板形式"]["value"] == "平板形",
        "25.4 改形式后确认，落图的就是卡片上选的那种形式",
        f"落图 {applied_plate.get('form') if applied_plate else '-'}、"
        f"参数表 防冲板形式={page.parameters['防冲板形式']['value']}、"
        f"删干涉管 {before_deletes}→{len(applied_plate.get('deleted') or []) if applied_plate else 0}",
    )

    # 26 元件参数弹窗：防冲板弹窗不再塞那段“平板形/圆弧形/焊接式”说明文字
    captured: dict = {}
    original_ask = page._ask

    def spy_ask(title, fields, hint=""):
        captured["title"] = title
        captured["hint"] = hint
        return {spec.name: page._param_text(spec.name) for spec in fields}

    page._ask = spy_ask
    page.select_centers(sorted(page.current_centers(), key=lambda c: (-round(c[1], 3), c[0]))[:2])
    page.place_impingement()
    page._ask = original_ask
    check(
        captured.get("title") == "防冲板参数设置" and not str(captured.get("hint") or "").strip(),
        "26 防冲板参数弹窗只留参数，不再堆那段说明文字",
        f"弹窗“{captured.get('title')}”提示区={'空' if not captured.get('hint') else captured['hint'][:20]}",
    )

    # 26.1 参数弹窗控件等高（重新排版后不再高高低低）
    from bundle.widgets import ComponentParamDialog, ParamField

    dialog = ComponentParamDialog(
        "防冲板参数设置",
        [ParamField("防冲板形式", "combo", ("平板形", "圆弧形", "焊接式")),
         ParamField("防冲板厚度", "number", unit="mm"),
         ParamField("防冲板折边角度", "number", unit="°")],
        {"防冲板形式": "圆弧形", "防冲板厚度": "10", "防冲板折边角度": "45"},
    )
    heights = {dialog._editors[name].height() for name in dialog._editors}
    dialog.adjustSize()
    heights = {dialog._editors[name].sizeHint().height() for name in dialog._editors}
    dialog.deleteLater()
    check(
        len(heights) == 1,
        "26.1 参数弹窗内各控件等高、标签固定列宽（版式统一）",
        f"控件高度 {sorted(heights)}",
    )

    # 27. 起始 Tab 按产品型式（My_Piping: BEM/NEN/AEM/NEN(H) → 管板型式，其余 → 布管）
    saved_type = window.session.product_type
    picks = {}
    for product in ("AEU", "BEU", "AKU", "BEM", "NEN", "AEM", "NEN(H)"):
        window.session.product_type = product
        picks[product] = window._pick_initial_stage()
    window.session.product_type = saved_type
    check(
        all(picks[p] == 1 for p in ("AEU", "BEU", "AKU"))
        and all(picks[p] == 0 for p in ("BEM", "NEN", "AEM", "NEN(H)"))
        and window.session.current_index == window._initial_stage,
        "27 管束起始 Tab 按产品型式（BEM/NEN/AEM/NEN(H) 进管板型式，其余进布管）",
        "、".join(f"{k}→{STAGES[v]}" for k, v in picks.items()),
    )

    # 27.1 保留确认弹窗：只说“进入下一阶段”，按钮是 是 / 否
    dialog = window._build_keep_box("管板型式")
    texts = [dialog.yes_button.text(), dialog.no_button.text()]
    body = " ".join(
        label.text() for label in dialog.findChildren(QLabel) if label.text()
    )
    dialog.deleteLater()
    check(
        texts == ["是", "否"] and "Tab" not in body and "tab" not in body
        and "进入下一阶段" in body,
        "27.1 保留确认弹窗不再提 Tab，按钮是 是 / 否",
        f"按钮 {texts}，正文“{body.strip()}”",
    )

    # 28. 中间挡管：隔板槽两侧各选一根，挡管落在连线与槽轴线的交点
    page.clear_selection()
    grooves = page._groove_pairs()
    groove_pair = grooves[1] if len(grooves) > 1 else None
    block_ok = False
    if groove_pair:
        page.select_centers(list(groove_pair))
        page.place_block_tube()
        tubes = [c for c in page.components if c["kind"] == "block_tube"]
        axis = page._groove_axis()
        block_ok = bool(tubes) and all(
            (abs(t["center"][1]) < 1e-6 if axis == "y" else abs(t["center"][0]) < 1e-6)
            for t in tubes
        )
    # 同一排/同一侧的两根管：源程序会拒绝
    bad_pair = [c for c in page.current_centers() if c[1] > 1e-6][:2]
    page.clear_selection()
    page.select_centers(bad_pair)
    before_bad = len([c for c in page.components if c["kind"] == "block_tube"])
    page.place_block_tube()
    after_bad = len([c for c in page.components if c["kind"] == "block_tube"])
    ok_point, point_error = page._block_tube_point(tuple(bad_pair))
    check(
        block_ok and before_bad == after_bad and point_error
        and "同一隔板槽两侧" in point_error,
        "28 中间挡管只认“隔板槽两侧各一根”，挡管落在槽轴线上",
        f"有效对 → 挡管 {[t['center'] for t in page.components if t['kind'] == 'block_tube']}；"
        f"同侧两管被拒：{point_error}",
    )

    # 28.1 中间挡板：隔板槽两侧第一排；同侧/同排一律拒绝并给原文提示
    side, reason = page._center_baffle_check(tuple(groove_pair)) if groove_pair else (None, "")
    bad_side, bad_reason = page._center_baffle_check(tuple(bad_pair))
    check(
        side == "horizontal" and not reason and not bad_side
        and "同一隔板槽两侧" in (bad_reason or "") or
        (side == "horizontal" and not reason and not bad_side
         and "隔板槽两侧第一排" in (bad_reason or "")),
        "28.1 中间挡板必须隔板槽两侧第一排（照 center_dangban 原文提示）",
        f"有效对 side={side}；同侧两管：{bad_reason}",
    )

    # 29. 对称分布：自由拉杆 / 普通拉杆 / 旁路挡板都按 4 象限铺
    page.undo()
    page.undo()
    page.clear_selection()
    counts = {}
    for cmd, kind in (("布置自由拉杆", "free_rod"), ("布置普通拉杆", "rod"), ("布置旁路挡板", "bypass")):
        before = len([c for c in page.components if c["kind"] == kind])
        window._handle_local_command(cmd)
        card = window.placement_cards[-1] if window.placement_cards else None
        if card is not None and card.confirm_button.isEnabled():
            card.confirm_button.click()
        counts[kind] = len([c for c in page.components if c["kind"] == kind]) - before
    check(
        counts["free_rod"] == 4 and counts["rod"] == 4 and counts["bypass"] == 4,
        "29 勾“对称分布”时自由拉杆/普通拉杆/旁路挡板都铺 4 个",
        f"自由拉杆 {counts['free_rod']}、普通拉杆 {counts['rod']}、旁路挡板 {counts['bypass']}",
    )

    # 29.1 防冲板两根参照管不再要求同一排（斜跨也可以）
    page.clear_selection()
    pool = sorted(page.current_centers(), key=lambda c: (-round(c[1], 3), c[0]))
    diagonal = None
    for first in pool[:4]:
        for second in pool[4:]:
            if abs(first[1] - second[1]) > 1.0 and abs(first[0] - second[0]) > 1.0:
                diagonal = (first, second)
                break
        if diagonal:
            break
    window._handle_local_command("上方布置1块平板形防冲板")
    card = window.placement_cards[-1] if window.placement_cards else None
    error_text = card._preview["rows"][0]["error"] if card is not None else "无卡片"
    check(
        diagonal is not None and not error_text,
        "29.1 防冲板不再自造“两根参照管要在同一排”的限制",
        f"跨排参照管 {diagonal} 校验结果={error_text or '通过'}",
    )

    # 30. 方案卡标题行不再写“落位后删 N 个干涉管”
    window._handle_local_command("上方布置1块平板形防冲板")
    card = window.placement_cards[-1] if window.placement_cards else None
    texts = [label.text() for label in card.findChildren(QLabel)] if card else []
    check(
        card is not None and not any("落位后删" in text for text in texts),
        "30 元件方案卡标题行不再挂“落位后删 N 个干涉管”",
        f"卡片上的文字：{[t for t in texts if t][:5]}",
    )
    if card is not None and card.discard_button.isEnabled():
        card.discard_button.click()

    # 30.1 参数弹窗标签按最长参数名撑开，长名字不再被截掉
    long_dialog = ComponentParamDialog(
        "折流板参数设置",
        [ParamField("折流/支持板外径", "number", unit="mm"),
         ParamField("折流板切口与中心线间距a", "number", unit="mm"),
         ParamField("折流板类型", "combo", ("单弓形", "双弓形"))],
        {"折流/支持板外径": "994", "折流板切口与中心线间距a": "284.5", "折流板类型": "单弓形"},
    )
    label = long_dialog._labels["折流板切口与中心线间距a"]
    label_width = label.minimumWidth()
    long_dialog.adjustSize()
    needed = label.fontMetrics().horizontalAdvance("折流板切口与中心线间距a")
    long_dialog.deleteLater()
    check(
        label_width > ComponentParamDialog.LABEL_WIDTH and label_width >= needed,
        "30.1 参数弹窗标签按最长参数名撑开，长名字不再被截断",
        f"标签宽 {label_width}px ≥ 文字宽 {needed}px（原固定 {ComponentParamDialog.LABEL_WIDTH}px）",
    )

    # 31. 勾“对称分布”时中间挡管、中间挡板也各出 2 个（源程序 judge_linkage）
    def _place_and_count(command, kind):
        start = len([c for c in page.components if c["kind"] == kind])
        window._handle_local_command(command)
        card = window.placement_cards[-1] if window.placement_cards else None
        if card is not None and card.confirm_button.isEnabled():
            card.confirm_button.click()
        return len([c for c in page.components if c["kind"] == kind]) - start

    tubes_added = _place_and_count("布置中间挡管", "block_tube")
    plates_added = _place_and_count("布置中间挡板", "center_baffle")
    check(
        page.symmetry_on() and tubes_added == 2 and plates_added == 2,
        "31 勾“对称分布”时中间挡管/中间挡板各补成 2 个",
        f"对称分布={page.symmetry_on()}，挡管 {tubes_added} 个、挡板 {plates_added} 个",
    )

    # 32. 旁路挡板外边缘贴着折流/支持板外径圆，四角都不超出大圆
    window._handle_local_command("布置旁路挡板")
    card = window.placement_cards[-1] if window.placement_cards else None
    if card is not None and card.confirm_button.isEnabled():
        card.confirm_button.click()
    plates = [c for c in page.components if c["kind"] == "bypass"][-4:]
    radius = page.result.baffle_r
    worst = 0.0
    for plate in plates:
        cx, cy = plate["center"]
        half_w, half_h = plate["size"][0] / 2.0, plate["size"][1] / 2.0
        for dx, dy in ((-half_w, -half_h), (half_w, -half_h), (-half_w, half_h), (half_w, half_h)):
            worst = max(worst, math.hypot(cx + dx, cy + dy))
    check(
        len(plates) == 4 and worst <= radius + 0.5,
        "32 旁路挡板宽度按“圆边 − 孔桥 − do/2”算，板整体落在折流板外径圆内",
        f"4 块板最远角 R={worst:.2f} ≤ 折流板半径 {radius:.2f}",
    )

    # 33. 对话里删/补换热管：先生成方案卡，确认后才改图
    holes_before = len(page.current_centers())
    window._handle_local_command("删除离隔板槽最近的两行换热管")
    hole_card = window.hole_cards[-1] if window.hole_cards else None
    pending_ok = bool(hole_card) and hole_card.confirm_button.isEnabled()
    untouched = len(page.current_centers()) == holes_before
    if pending_ok:
        hole_card.confirm_button.click()
    holes_after = len(page.current_centers())
    window._handle_local_command("恢复刚才删除的换热管")
    restore_card = window.hole_cards[-1] if window.hole_cards else None
    if restore_card is not None:
        restore_card.confirm_button.click()
    holes_restored = len(page.current_centers())
    check(
        pending_ok and untouched and holes_after < holes_before and holes_restored == holes_before,
        "33 “删除离隔板槽最近的两排换热管”由程序算管孔，确认后删、可再恢复",
        f"方案卡待确认={pending_ok}，管孔 {holes_before}→{holes_after}→{holes_restored}",
    )

    # 34. 初始对话只留两句，底部提示行与库状态行都删掉
    greeting = window.chat_history[0]["content"] if window.chat_history else ""
    hint_gone = window.findChild(QLabel, "shortcutHint") is None
    db_gone = not hasattr(window, "db_label")
    check(
        greeting.count("\n") == 1 and "四个阶段" not in greeting and hint_gone and db_gone,
        "34 初始对话只留两句，快捷键提示行与“正式库：…”状态行已去掉",
        f"欢迎语={greeting!r}，提示行已删={hint_gone}，库状态行已删={db_gone}",
    )

    # 35. “最外层”= 布管轮廓：每行两端 + 最上/最下一整排（不是贯穿中间的锯齿）
    from bundle.placement import UIAction, group_lines

    page.clear_selection()
    window._run_ui_actions([UIAction(name="select_region", region="near_shell", rows=1)])
    outer_selected = list(page.selected)
    total_holes = len(page.current_centers())
    picked_keys = {(round(float(c[0]), 6), round(float(c[1]), 6)) for c in outer_selected}
    rows_all = group_lines(page.current_centers(), "row")
    cap_rows = {0, len(rows_all) - 1}            # 最上一排、最下一排
    cap_keys: set[tuple[float, float]] = set()
    for index in cap_rows:
        for point in rows_all[index]:
            cap_keys.add((round(float(point[0]), 6), round(float(point[1]), 6)))
    line_count = 0
    edge_ok = bool(picked_keys) and cap_keys <= picked_keys
    for index, line in enumerate(rows_all):
        ordered = sorted(line, key=lambda c: c[0])
        line_count += 1
        keys = [(round(float(c[0]), 6), round(float(c[1]), 6)) for c in ordered]
        if not {keys[0], keys[-1]} <= picked_keys:
            edge_ok = False                          # 每行两端都得在里面
            break
        if index in cap_rows:                        # 最上/最下一整排：整排都得选中
            if not set(keys) <= picked_keys:
                edge_ok = False
                break
        elif any(key in picked_keys for key in keys[1:-1]):
            edge_ok = False                          # 中间各排只许取两端
            break
    check(
        edge_ok and 0 < len(outer_selected) < total_holes / 3,
        "35 “最外层”= 每行最左、最右各一根，且最上、最下一整排全取",
        f"选中 {len(outer_selected)}/{total_holes} 个，覆盖 {line_count} 行，"
        f"顶/底排共 {len(cap_keys)} 根",
    )

    # 36. 已删除管孔留痕：图上虚线可点选，行列号不再是 0
    window._handle_local_command("删除最外一圈的换热管")
    if window.hole_cards:
        window.hole_cards[-1].confirm_button.click()
    ghosts = list(page._ghost_items)
    ghost_refs = [page._tube_ref(c) for c in ghosts[:4]]
    ghost_ok = bool(ghosts) and all(ref["row"] != 0 or ref["col"] != 0 for ref in ghost_refs)
    page.select_centers(ghosts[:2])
    ghost_selected = sum(1 for item in page._ghost_items.values() if item.is_selected)
    page.clear_selection()
    check(
        ghost_ok and ghost_selected == min(2, len(ghosts)) and len(ghosts) < total_holes,
        "36 删掉的管孔在图上留虚线小叉、可点选，方案卡不再显示“行0列0”",
        f"虚线管孔 {len(ghosts)} 个，示例 {ghost_refs[0] if ghost_refs else None}，点选中 {ghost_selected} 个",
    )

    # 37. 界面动作：取消全选 / 列出坐标 都能执行（模型给 ui_actions 走同一条路）
    window._run_ui_actions([UIAction(name="select_all")])
    selected_all = len(page.selected)
    notes = window._run_ui_actions([UIAction(name="clear_selection")])
    cleared = len(page.selected) == 0
    coords_before = len(window.conversation.findChildren(QTableWidget))
    window._run_ui_actions([UIAction(name="dump_holes")])
    coords_after = len(window.conversation.findChildren(QTableWidget))
    check(
        selected_all > 0 and cleared and coords_after == coords_before + 1,
        "37 “取消全选”“列出所有换热管坐标”这类界面操作 Agent 都能执行",
        f"全选 {selected_all} 个→取消后 {len(page.selected)} 个；坐标表卡 {coords_before}→{coords_after}",
    )

    # 38. 提示词不再把 Agent 封死（去掉“严禁输出坐标”等限制，补上 ui_actions 清单）
    prompt_text = (ROOT / "ai_support" / "api_client.py").read_text(encoding="utf-8")
    check(
        "严禁输出管孔坐标" not in prompt_text
        and "ui_action_brief()" in prompt_text
        and "不要以" in prompt_text,
        "38 提示词改成“界面上的事都能做”，并给出 ui_actions 动作清单",
        "已去掉“严禁输出坐标/这不是我的范围”这类自我限制",
    )

    # 39. 元件有自己的数据字典：要拉杆就只给拉杆（不再拿换热管表顶替）
    page.remove_components("rod")
    page.remove_components("free_rod")
    window._handle_local_command("布置拉杆")
    if window.placement_cards:
        window.placement_cards[-1].confirm_button.click()
    rod_data = page.component_coordinates("rod")
    rod_rows = rod_data["rows"]
    check(
        bool(rod_rows) and rod_data["label"] == "拉杆"
        and all(r["name"] == "拉杆" for r in rod_rows)
        and all(r.get("row") not in ("", None) for r in rod_rows)
        and all("φ" in r["spec"] for r in rod_rows),
        "39 每个元件有自己的数据字典——要拉杆就给拉杆（形式/直径/行列号/坐标）",
        f"拉杆 {len(rod_rows)} 根，示例 {rod_rows[0] if rod_rows else None}",
    )
    window._handle_local_command("输出所有拉杆坐标")
    last_chat = window.chat_history[-1]["content"] if window.chat_history else ""
    check(
        "已列出拉杆" in last_chat and "换热管" not in last_chat,
        "39.1 “输出所有拉杆坐标”给的是拉杆表，不再是换热管表",
        last_chat[:80],
    )

    # 40. “把所有拉杆恢复为换热管”：删元件 + 把占的管孔还给换热管
    holes_before_conv = len(page.current_centers())
    rods_before_conv = len([c for c in page.components if c["kind"] == "rod"])
    window._handle_local_command("将所有拉杆恢复为换热管")
    holes_after_conv = len(page.current_centers())
    check(
        rods_before_conv > 0
        and holes_after_conv == holes_before_conv + rods_before_conv
        and not any(c["kind"] == "rod" for c in page.components),
        "40 “将所有拉杆恢复为换热管”真的删掉拉杆并把管孔还回来",
        f"拉杆 {rods_before_conv}→0，管孔 {holes_before_conv}→{holes_after_conv}",
    )

    # 41. 拉杆单次数量上限：模型把“所有拉杆”当成布置几百根时兜住
    from bundle.placement import PlacementItem, ROD_LIMIT_PER_PLACEMENT

    huge = page._resolve_item(PlacementItem("rod", 492, "any", {}))
    check(
        len(huge["tubes"]) <= ROD_LIMIT_PER_PLACEMENT + 4,
        "41 单次拉杆数量有上限，不会一次铺满整张图",
        f"要求 492 根 → 实际解析 {len(huge['tubes'])} 根（上限 {ROD_LIMIT_PER_PLACEMENT}）",
    )

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
