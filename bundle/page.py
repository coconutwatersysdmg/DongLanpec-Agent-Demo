"""布管页面：左侧参数表 + 中间布管图形 + 右侧管孔数量分布表 + 底部“保留”。

图形、表格、参数三者共用同一份状态：
    master_centers  正式程序布管接口算出的全部管孔
    removed         被删除/被拉杆等元件占用的管孔
    components      元件（拉杆、旁路挡板、滑道……）
任何一处变化都会刷新图形与右侧数量表，因此“整行选中 / 数量统计 / 元件显示”
始终一致，不存在只做样式的静态图。
"""
from __future__ import annotations

import math
from copy import deepcopy

from PyQt5.QtCore import QPointF, QRectF, QSize, Qt, pyqtSignal
from PyQt5.QtGui import QBrush, QColor, QFont, QIcon, QPainterPath, QPen, QPixmap
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGraphicsEllipseItem,
    QGraphicsLineItem,
    QGraphicsPathItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import engine, geometry
from .hole_table import HoleDistributionTable
from .items import (
    BYPASS_COLOR,
    CENTER_BAFFLE_COLOR,
    IMPINGE_COLOR,
    SLIDE_COLOR,
    BlockTubeItem,
    ComponentRectItem,
    RadialHoleItem,
    RodItem,
    TubeItem,
)
from .params import (
    DERIVED_FIELDS,
    PARAM_ORDER,
    TIE_ROD_DIAMETERS,
    layout_hidden_params,
    spec_for,
    tube_pattern_image,
)
from .view import LayoutGraphicsView
from .widgets import ParamField, TubePassFormComboBox, ask_component_params

STATIC_DIR = __import__("pathlib").Path(__file__).resolve().parent / "static"

# 管程分程形式行：示意图要看得清，行高与值列都比普通行宽
PATTERN_ROW_HEIGHT = 60
PATTERN_COLUMN_WIDTH = 220

COMPONENT_KIND_TO_TYPE = {
    "rod": 0,
    "free_rod": 1,
    "block_tube": 2,
    "bypass": 3,
    "center_baffle": 4,
    "impingement": 5,
    "impingement_folded": 6,
    "slide": 8,
}
COMPONENT_LABEL = {
    "rod": "拉杆",
    "free_rod": "自由拉杆",
    "block_tube": "中间挡管",
    "bypass": "旁路挡板",
    "center_baffle": "中间挡板",
    "impingement": "防冲板",
    "impingement_folded": "折边式防冲板",
    "slide": "滑道",
    "screw_ring": "吊环螺钉",
    "radial_hole": "径向开孔",
}


def _describe_rows(rows: list[int]) -> str:
    """把选中的行下标写成人话：第 3 行 / 第 3、5 行 / 第 3–7 行 / 第 3 行等 6 行。"""
    numbers = sorted({row + 1 for row in rows})
    if not numbers:
        return "第 0 行"
    if len(numbers) == 1:
        return f"第 {numbers[0]} 行"
    if numbers == list(range(numbers[0], numbers[-1] + 1)):
        return f"第 {numbers[0]}–{numbers[-1]} 行"
    if len(numbers) <= 4:
        return "第 " + "、".join(str(n) for n in numbers) + " 行"
    return f"第 {numbers[0]} 行等 {len(numbers)} 行"


class TubeLayoutPage(QWidget):
    keep_requested = pyqtSignal()
    state_changed = pyqtSignal(dict)
    status_message = pyqtSignal(str)
    selected_count_changed = pyqtSignal(int)

    def __init__(self, parameters: dict, product_type: str, defaults: dict | None = None,
                 center_distance_rows: list[list[str]] | None = None, sheet_form: dict | None = None,
                 parent=None):
        super().__init__(parent)
        self.product_type = (product_type or "AEU").strip().upper()
        self.defaults = defaults or {}
        self.center_distance_rows = center_distance_rows or []
        self.sheet_form = sheet_form or {}
        self.parameters: dict[str, dict] = {}
        for name in PARAM_ORDER:
            row = (parameters or {}).get(name) or {}
            self.parameters[name] = {
                "value": row.get("value", ""),
                "unit": row.get("unit", ""),
                "source": row.get("source", "程序默认值"),
                "editable": True,
            }
        self.result: engine.LayoutResult | None = None
        self.removed: set[tuple[float, float]] = set()
        self.components: list[dict] = []
        self.selected: set[tuple[float, float]] = set()
        self.selected_component: int | None = None
        self.issues: list[dict] = []
        self._undo: list[dict] = []
        self._tube_items: dict[tuple[float, float], TubeItem] = {}
        self._component_items: dict[int, ComponentRectItem] = {}
        self._rows_pos: list[list[tuple[float, float]]] = []
        self._rows_neg: list[list[tuple[float, float]]] = []
        self._cols_right: list[list[tuple[float, float]]] = []
        self._cols_left: list[list[tuple[float, float]]] = []
        self._editors: dict[str, QWidget] = {}
        self._suppress_commit = False
        # 离屏自动验收时置 True：不弹模态框，改为在操作栏提示
        self.headless = False
        self._build_ui()
        self.rebuild_parameter_table()
        self.recompute(first=True)

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(10)

        # 元件工具条：整页顶部独占一行，避免挤占中间图形的宽度
        toolbar = QHBoxLayout()
        toolbar.setSpacing(4)
        tool_specs = [
            ("换热管", "button1_1.png", self.restore_tubes),
            ("拉杆", "button1_2.png", lambda: self.place_rod(free=False)),
            ("自由拉杆", "button1_3.png", lambda: self.place_rod(free=True)),
            ("中间挡管", "button2_1.png", self.place_block_tube),
            ("旁路挡板", "button2_2.png", lambda: self.place_plate("bypass")),
            ("滑道", "button2_3.png", self.place_slide),
            ("吊环螺钉", "button3_1.png", self.place_screw_ring),
            ("中间挡板", "button3_2.png", lambda: self.place_plate("center_baffle")),
            ("防冲板", "button3_3.png", self.place_impingement),
            ("折流板", "button3_4.png", self.place_baffle),
            ("径向开孔", "button3_5.png", self.place_radial_hole),
            ("删除", "button1_4.png", self.delete_selected),
        ]
        for text, icon, slot in tool_specs:
            button = QPushButton(text)
            button.setCursor(Qt.PointingHandCursor)
            icon_path = STATIC_DIR / "buttons" / icon
            if icon_path.exists():
                button.setIcon(QIcon(str(icon_path)))
            button.setIconSize(QSize(16, 16))
            button.setStyleSheet(
                "QPushButton{background:#ffffff;border:1px solid #e2e3e6;border-radius:6px;"
                "padding:3px 6px;font-size:9pt;color:#222;}"
                "QPushButton:hover{background:#f2f6fd;border-color:#c9dbfb;}"
            )
            button.clicked.connect(slot)
            toolbar.addWidget(button)
        toolbar.addStretch()
        root.addLayout(toolbar)

        # 左：参数表
        left = QFrame()
        left.setObjectName("layoutParamFrame")
        left.setMinimumWidth(360)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(4, 4, 4, 4)
        left_layout.setSpacing(4)
        self.param_table = QTableWidget(0, 4)
        self.param_table.setFont(QFont("Microsoft YaHei UI", 9))
        self.param_table.setHorizontalHeaderLabels(["序号", "参数名称", "参数值", "单位"])
        self.param_table.verticalHeader().setVisible(False)
        self.param_table.verticalHeader().setDefaultSectionSize(28)
        self.param_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.param_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.param_table.setAlternatingRowColors(True)
        header = self.param_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.Fixed)
        header.setSectionResizeMode(3, QHeaderView.Fixed)
        self.param_table.setColumnWidth(0, 30)
        self.param_table.setColumnWidth(2, PATTERN_COLUMN_WIDTH)
        self.param_table.setColumnWidth(3, 36)
        header.setMinimumSectionSize(30)
        left_layout.addWidget(self.param_table, 1)
        self.lagan_summary = QLabel("拉杆标准要求数量-/已有数量0")
        self.lagan_summary.setStyleSheet("color:#222; padding:4px 6px;")
        left_layout.addWidget(self.lagan_summary)
        body.addWidget(left, 36)

        # 中：图形 + 操作栏
        center = QFrame()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(4, 4, 4, 4)
        center_layout.setSpacing(4)

        self.scene = QGraphicsScene(self)
        self.view = LayoutGraphicsView(self.scene)
        self.view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.view.setMinimumHeight(240)
        self.view.rubber_band_finished.connect(self.on_rubber_band)
        # 正式程序：页面/图形空白处右键 = 取消筛选（清掉表格与图形的选中）
        self.view.clear_selection_requested.connect(self.clear_selection)
        center_layout.addWidget(self.view, 1)

        action_bar = QHBoxLayout()
        action_bar.setSpacing(6)
        self.pipe_button = QPushButton("布管")
        self.pipe_button.setCursor(Qt.PointingHandCursor)
        self.pipe_button.setStyleSheet(
            "QPushButton{background:#2f6fe4;color:#fff;border:none;border-radius:7px;padding:6px 16px;font-weight:600;}"
            "QPushButton:hover{background:#2a63cc;}"
        )
        self.pipe_button.clicked.connect(lambda: self.recompute(reason="用户点击布管"))
        action_bar.addWidget(self.pipe_button)
        for text, slot in (("撤销", self.undo), ("重绘", self.rebuild_scene), ("全屏", self.toggle_fullscreen)):
            button = QPushButton(text)
            button.setCursor(Qt.PointingHandCursor)
            button.setStyleSheet(
                "QPushButton{background:#fff;border:1px solid #e2e3e6;border-radius:7px;padding:5px 12px;}"
                "QPushButton:hover{background:#f5f7fa;}"
            )
            button.clicked.connect(slot)
            action_bar.addWidget(button)
        action_bar.addStretch()
        self.selection_label = QLabel("未选中管孔")
        self.selection_label.setStyleSheet("color:#8f949c;")
        action_bar.addWidget(self.selection_label)
        center_layout.addLayout(action_bar)
        body.addWidget(center, 39)

        # 右：管孔数量分布
        right = QFrame()
        right.setMinimumWidth(340)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(4, 4, 4, 4)
        self.hole_table = HoleDistributionTable()
        self.hole_table.rows_selected.connect(self.on_table_rows_selected)
        self.hole_table.arrangement_changed.connect(lambda _by_row: self.refresh_hole_table())
        right_layout.addWidget(self.hole_table)
        body.addWidget(right, 25)

        root.addLayout(body, 1)

        # 校验问题 + 唯一的“保留”按钮
        self.issue_frame = QFrame()
        self.issue_frame.setObjectName("layoutIssueFrame")
        self.issue_frame.setStyleSheet(
            "QFrame#layoutIssueFrame{background:#fff8f7;border:1px solid #f0ceca;border-radius:8px;}"
        )
        issue_layout = QVBoxLayout(self.issue_frame)
        issue_layout.setContentsMargins(10, 8, 10, 8)
        issue_layout.setSpacing(4)
        self.issue_title = QLabel("需要修改")
        self.issue_title.setStyleSheet("font-weight:600;color:#9b2c2c;")
        issue_layout.addWidget(self.issue_title)
        self.issue_list = QLabel("")
        self.issue_list.setWordWrap(True)
        self.issue_list.setTextInteractionFlags(Qt.TextSelectableByMouse)
        issue_layout.addWidget(self.issue_list)
        self.recommend_box = QHBoxLayout()
        self.recommend_box.setContentsMargins(0, 0, 0, 0)
        self.recommend_box.addStretch()
        issue_layout.addLayout(self.recommend_box)
        self.issue_frame.hide()
        root.addWidget(self.issue_frame)

        footer = QHBoxLayout()
        footer.addStretch()
        self.keep_button = QPushButton("保留")
        self.keep_button.setCursor(Qt.PointingHandCursor)
        self.keep_button.setMinimumWidth(120)
        self.keep_button.setStyleSheet(
            "QPushButton{background:#2f6fe4;color:#fff;border:none;border-radius:9px;padding:9px 26px;"
            "font-weight:600;font-size:10.5pt;}"
            "QPushButton:hover{background:#2a63cc;}"
            "QPushButton:disabled{background:#eef2fa;color:#a8b6cc;}"
        )
        self.keep_button.clicked.connect(self.keep_requested.emit)
        footer.addWidget(self.keep_button)
        root.addLayout(footer)

    # ------------------------------------------------------ 参数表
    def rebuild_parameter_table(self) -> None:
        table = self.param_table
        self._suppress_commit = True
        try:
            for row in range(table.rowCount()):
                widget = table.cellWidget(row, 2)
                if widget is not None:
                    table.removeCellWidget(row, 2)
                    widget.deleteLater()
            table.setRowCount(len(PARAM_ORDER))
            self._editors = {}
            for row, name in enumerate(PARAM_ORDER):
                spec = spec_for(name, self.product_type, self.parameters)
                data = self.parameters[name]
                seq = QTableWidgetItem(str(row + 1))
                seq.setTextAlignment(Qt.AlignCenter)
                seq.setFlags(Qt.ItemIsEnabled)
                table.setItem(row, 0, seq)
                label = QTableWidgetItem(name)
                label.setFlags(Qt.ItemIsEnabled)
                label.setToolTip(name)
                table.setItem(row, 1, label)
                unit = QTableWidgetItem(data.get("unit", "") or spec.unit)
                unit.setTextAlignment(Qt.AlignCenter)
                unit.setFlags(Qt.ItemIsEnabled)
                table.setItem(row, 3, unit)
                placeholder = QTableWidgetItem("")
                placeholder.setFlags(Qt.ItemIsEnabled)
                table.setItem(row, 2, placeholder)
                editor = self._make_editor(name, spec, data)
                table.setCellWidget(row, 2, editor)
                self._editors[name] = editor
                table.setRowHeight(row, 28)
                self._paint_param_row(row, name)
            pattern_row = PARAM_ORDER.index("管程分程形式")
            table.setRowHeight(pattern_row, PATTERN_ROW_HEIGHT)
            self.apply_param_visibility()
        finally:
            self._suppress_commit = False
        self._lock_outer_base_flag()

    def _make_editor(self, name: str, spec, data: dict) -> QWidget:
        value = "" if data.get("value") is None else str(data.get("value"))
        readonly = spec.readonly
        if spec.kind == "pattern":
            # 正式程序 TubePassFormComboBox：显示示意图，不是数字/文字
            combo = TubePassFormComboBox()
            items = list(spec.options)
            if value and value not in items:
                # 库里留着历史值（如 4.3）：照样补一项并配它的示意图
                items.append(value)
            for option in items:
                image = tube_pattern_image(option)
                path = STATIC_DIR / "TubePattern" / image if image else None
                pixmap = QPixmap(str(path)) if path is not None and path.exists() else QPixmap()
                combo.addItem("", option)
                combo.setItemData(combo.count() - 1, option, Qt.UserRole)
                if not pixmap.isNull():
                    combo.setItemData(combo.count() - 1, pixmap, TubePassFormComboBox.PIXMAP_ROLE)
            index = combo.findData(value) if value else -1
            if index >= 0:
                combo.setCurrentIndex(index)
            combo.setEnabled(not readonly)
            combo.activated.connect(lambda _i, n=name, c=combo: self._commit_param(n, c.currentData()))
            return combo
        if spec.kind == "combo" and spec.options:
            combo = QComboBox()
            combo.setEditable(False)
            for option in spec.options:
                combo.addItem(option, option)
            index = combo.findData(value) if value else -1
            if index < 0 and value:
                # 正式程序遇到表里没有的历史值时保留显示，但不允许再选新值
                combo.addItem(value, value)
                index = combo.count() - 1
            if index >= 0:
                combo.setCurrentIndex(index)
            combo.setEnabled(not readonly)
            combo.activated.connect(lambda _i, n=name, c=combo: self._commit_param(n, c.currentData()))
            return combo
        if spec.kind == "combo_edit":
            combo = QComboBox()
            combo.setEditable(True)
            for option in spec.options:
                combo.addItem(option)
            if value:
                combo.setEditText(value)
            combo.setEnabled(not readonly)
            combo.activated.connect(lambda _i, n=name, c=combo: self._commit_param(n, c.currentText()))
            combo.lineEdit().editingFinished.connect(
                lambda n=name, c=combo: self._commit_param(n, c.currentText())
            )
            return combo
        edit = QLineEdit(value)
        edit.setEnabled(not readonly)
        edit.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        if readonly:
            edit.setStyleSheet("QLineEdit{background:#f4f6f8;color:#6b7280;}")
        edit.editingFinished.connect(lambda n=name, e=edit: self._commit_param(n, e.text()))
        return edit

    def _paint_param_row(self, row: int, name: str) -> None:
        data = self.parameters[name]
        spec = spec_for(name, self.product_type, self.parameters)
        item = self.param_table.item(row, 2)
        if item is None:
            return
        issue = next((x for x in self.issues if x.get("field") == name), None)
        if issue:
            item.setBackground(QColor("#ffe4e2"))
            item.setToolTip(issue.get("message", ""))
        elif name in DERIVED_FIELDS:
            item.setBackground(QColor("#eef3f8"))
            item.setToolTip("由程序联动计算")
        else:
            item.setBackground(QColor("#ffffff"))
            item.setToolTip("")
        editor = self._editors.get(name)
        if editor is not None:
            base = "QLineEdit{background:#ffffff;border:1px solid #e6e5e2;border-radius:4px;padding:2px 6px;}"
            error = "QLineEdit{background:#fff5f5;border:1px solid #d04b4b;border-radius:4px;padding:2px 6px;}"
            readonly = "QLineEdit{background:#f4f6f8;color:#6b7280;border:1px solid #eef0f3;border-radius:4px;padding:2px 6px;}"
            if isinstance(editor, QLineEdit):
                editor.setStyleSheet(error if issue else (readonly if spec.readonly else base))
            elif isinstance(editor, QComboBox):
                combo_style = (
                    "QComboBox{background:#ffffff;border:1px solid #e6e5e2;border-radius:4px;padding:2px 18px 2px 6px;}"
                    "QComboBox:hover{border-color:#c9d8ea;}"
                )
                if issue:
                    combo_style = "QComboBox{background:#fff5f5;border:1px solid #d04b4b;border-radius:4px;padding:2px 18px 2px 6px;}"
                if name == "是否以外径为基准":
                    # 该行与正式程序一致：只读灰显，鼠标也无法操作
                    combo_style = (
                        "QComboBox{background:#f4f6f8;color:#969696;border:1px solid #eef0f3;"
                        "border-radius:4px;padding:2px 18px 2px 6px;}"
                    )
                editor.setStyleSheet(combo_style)
                editor.setToolTip(issue.get("message", "") if issue else "")
            if issue:
                editor.setToolTip(issue.get("message", ""))

    # ------------------------------------------------------ 参数提交与联动
    def set_parameter(self, name: str, value, source: str = "人工修改", run_linkage: bool = True) -> bool:
        if name not in self.parameters:
            return False
        spec = spec_for(name, self.product_type, self.parameters)
        text = "" if value is None else str(value).strip()
        # 与正式程序一致：普通下拉只能是现有选项；只读参数不接受修改；数字必须能转成数
        if spec.readonly and source not in {"联动计算", "程序默认值"}:
            if str(self.parameters[name].get("value", "")) != text:
                self._warn("参数只读", f"{name} 由其他参数联动计算，不能直接修改。")
                self._refresh_editor(name)
                return False
        if spec.kind == "combo" and spec.options:
            if text and text not in spec.options:
                self._warn(
                    "无效选项",
                    f"{name} 是普通下拉框，只能从现有 {len(spec.options)} 个选项中选择，"
                    f"已拒绝“{text}”。",
                )
                self._refresh_editor(name)
                return False
        if spec.kind == "number" and text:
            try:
                float(text)
            except ValueError:
                self._warn("输入无效", f"{name} 必须填写数字，已拒绝“{text}”。")
                self._refresh_editor(name)
                return False
        if spec.kind == "combo_edit" and text and text != "程序推荐":
            try:
                float(text)
            except ValueError:
                self._warn("输入无效", f"{name} 只能填“程序推荐”或数字，已拒绝“{text}”。")
                self._refresh_editor(name)
                return False
        old = self.parameters[name]["value"]
        self.parameters[name]["value"] = value
        self.parameters[name]["source"] = source
        if run_linkage:
            self._apply_linkage(name)
        editor = self._editors.get(name)
        text = "" if value is None else str(value)
        if isinstance(editor, QLineEdit) and editor.text() != text:
            editor.setText(text)
        elif isinstance(editor, QComboBox):
            if str(editor.currentData()) != str(value):
                index = editor.findData(value)
                if index < 0:
                    index = editor.findText(text)
                if index >= 0 and editor.currentIndex() != index:
                    editor.setCurrentIndex(index)
        self.state_changed.emit({"parameter": name, "old": old, "value": value})
        return str(old) != str(value)

    def _commit_param(self, name: str, raw_value) -> None:
        if self._suppress_commit:
            return
        text = "" if raw_value is None else str(raw_value).strip()
        spec = spec_for(name, self.product_type, self.parameters)
        if spec.kind == "combo" and spec.options:
            if text and text not in spec.options:
                self._warn("不能输入", f"{name} 是普通下拉框，只能从现有选项中选择。")
                self._refresh_editor(name)
                return
        if spec.kind in {"number"} and text:
            try:
                float(text)
            except ValueError:
                self._warn("输入无效", f"{name} 必须填写数字。")
                self._refresh_editor(name)
                return
        if spec.kind == "combo_edit" and text and text != "程序推荐":
            try:
                float(text)
            except ValueError:
                self._warn("输入无效", f"{name} 只能填“程序推荐”或数字。")
                self._refresh_editor(name)
                return
        changed = self.set_parameter(name, text)
        if changed:
            self.recompute(reason=f"修改 {name}")
        else:
            self._refresh_editor(name)

    def _warn(self, title: str, text: str, kind: str = "warning") -> None:
        if self.headless:
            self.status_message.emit(f"{title}：{text}")
            return
        if kind == "info":
            QMessageBox.information(self, title, text)
        else:
            QMessageBox.warning(self, title, text)

    def _refresh_editor(self, name: str) -> None:
        editor = self._editors.get(name)
        value = self.parameters[name]["value"]
        if editor is None:
            return
        self._suppress_commit = True
        try:
            if isinstance(editor, QLineEdit):
                editor.setText("" if value is None else str(value))
            elif isinstance(editor, QComboBox):
                if str(editor.currentData()) == str(value):
                    return
                index = editor.findData(value)
                if index < 0:
                    index = editor.findText(str(value))
                if index >= 0:
                    editor.setCurrentIndex(index)
        finally:
            self._suppress_commit = False

    # ------------------------------------------------------ 参数显隐（正式程序同逻辑）
    def apply_param_visibility(self) -> None:
        """按正式程序的 hidden_params / update_SN / 直径基准规则隐藏参数行。"""
        hidden = layout_hidden_params(self.parameters)
        table = self.param_table
        for row, name in enumerate(PARAM_ORDER):
            table.setRowHidden(row, name in hidden)
        self._renumber_rows()

    def _renumber_rows(self) -> None:
        """隐藏行不占序号：可见行从 1 连续编号（正式程序 renumber_visible_rows）。"""
        visible = 0
        for row in range(self.param_table.rowCount()):
            if self.param_table.isRowHidden(row):
                continue
            visible += 1
            item = self.param_table.item(row, 0)
            if item is not None:
                item.setText(str(visible))

    def _lock_outer_base_flag(self) -> None:
        """正式程序：是否以外径为基准在布管页只读灰显，不在界面手工修改。"""
        editor = self._editors.get("是否以外径为基准")
        if isinstance(editor, QComboBox):
            editor.setEnabled(False)
            editor.setFocusPolicy(Qt.NoFocus)
            editor.setStyleSheet("QComboBox:disabled{color:#969696;background:#f4f6f8;}")
            editor.setToolTip("由设计数据表/通用数据表决定，布管页不可修改")

    def _apply_linkage(self, changed: str) -> None:
        """正式程序的参数联动：DN→Dis/Dit，Dis→折流板外径/DL，do+排列→S/Sn，管程→分程形式。"""
        dn = self._float("公称直径 DN")
        dis = self._float("壳体内直径 Dis")
        r2 = self._float_from_sheet_form("R2", 8.0)

        if changed == "公称直径 DN" and dn:
            if self.parameters["壳体内直径 Dis"]["source"] in {"程序默认值", "联动计算"}:
                self.set_parameter("壳体内直径 Dis", self._pretty(dn), "联动计算", run_linkage=False)
            if self.parameters["管箱内直径 Dit"]["source"] in {"程序默认值", "联动计算"}:
                self.set_parameter("管箱内直径 Dit", self._pretty(dn), "联动计算", run_linkage=False)
            dis = self._float("壳体内直径 Dis")
        if changed in {"壳体内直径 Dis", "公称直径 DN"} and dis:
            if self.parameters["折流/支持板外径"]["source"] in {"程序默认值", "联动计算"}:
                # 正式程序：折流/支持板外径 = 壳体内直径 - 6（见默认表 1144→1138）
                self.set_parameter("折流/支持板外径", self._pretty(dis - 6), "联动计算", run_linkage=False)
            if self.parameters["布管限定圆 DL"]["source"] in {"程序默认值", "联动计算"}:
                dl = max(dis - 2 * r2, 0)
                self.set_parameter("布管限定圆 DL", self._pretty(dl), "联动计算", run_linkage=False)
        if changed in {"换热管外径 do", "换热管排列方式"}:
            self._apply_center_distance()
        if changed == "管程程数":
            forms = spec_for("管程分程形式", self.product_type, self.parameters).options
            current = str(self.parameters["管程分程形式"]["value"])
            if forms and current not in forms:
                self.set_parameter("管程分程形式", forms[0], "联动计算", run_linkage=False)
            self._rebuild_editor_options("管程分程形式")
        if changed in {"是否以外径为基准", "管程程数", "管程分程形式"}:
            # 与正式程序一致：这几个参数变化后重算哪些行该隐藏
            self.apply_param_visibility()

    def _rebuild_editor_options(self, name: str) -> None:
        old = self._editors.get(name)
        if old is None:
            return
        row = PARAM_ORDER.index(name)
        spec = spec_for(name, self.product_type, self.parameters)
        new = self._make_editor(name, spec, self.parameters[name])
        self.param_table.removeCellWidget(row, 2)
        old.deleteLater()
        self.param_table.setCellWidget(row, 2, new)
        self._editors[name] = new

    def _apply_center_distance(self) -> None:
        if not self.center_distance_rows:
            return
        do = self._float("换热管外径 do")
        arrangement = str(self.parameters["换热管排列方式"]["value"] or "")
        if not do:
            return
        triangle = arrangement in {"正三角形", "转角正三角形"}
        header = self.center_distance_rows[0]
        try:
            index = header.index("换热管外径d")
        except ValueError:
            return
        row_s = self.center_distance_rows[1] if triangle else self.center_distance_rows[2]
        row_sn = self.center_distance_rows[3] if len(self.center_distance_rows) > 3 else None
        do_text = self._pretty(do)
        if do_text not in header:
            return
        position = header.index(do_text)
        if position >= len(row_s):
            return
        if self.parameters["换热管中心距 S"]["source"] in {"程序默认值", "联动计算"}:
            self.set_parameter("换热管中心距 S", row_s[position], "联动计算", run_linkage=False)
        if row_sn and position < len(row_sn) and self.parameters["分程隔板两侧相邻管中心距（竖直）"]["source"] in {"程序默认值", "联动计算"}:
            self.set_parameter("分程隔板两侧相邻管中心距（竖直）", row_sn[position], "联动计算", run_linkage=False)

    def _float(self, name: str) -> float | None:
        try:
            return float(str(self.parameters.get(name, {}).get("value", "")).strip())
        except (TypeError, ValueError):
            return None

    def _float_from_sheet_form(self, symbol: str, default: float) -> float:
        try:
            return float(str(self.sheet_form.get(symbol, default)).strip())
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _pretty(value: float) -> str:
        number = float(value)
        return str(int(number)) if number.is_integer() else f"{number:.1f}"

    # ------------------------------------------------------ 计算 + 绘制
    def recompute(self, reason: str = "", first: bool = False) -> bool:
        self._push_undo()
        try:
            result = engine.compute(self.parameters, self.product_type, self.defaults)
        except Exception as exc:  # noqa: BLE001 - 需要把真实原因展示给用户
            self.issues = [{"field": "换热管中心距 S", "message": str(exc), "recommended": None}]
            self.show_issues()
            self.status_message.emit(f"布管失败：{exc}")
            return False
        self.result = result
        known = set(result.master_centers)
        self.removed &= known
        self.issues = engine.check_geometry(self.parameters, result)
        self.rebuild_scene()
        self.refresh_hole_table()
        self.show_issues()
        if reason:
            total = len(self.current_centers())
            self.status_message.emit(f"{reason}：已重新布管，当前 {total} 个管孔")
        return not self.issues

    def current_centers(self) -> list[tuple[float, float]]:
        if self.result is None:
            return []
        occupied = {c["center"] for c in self.components if c.get("center")}
        return [
            c for c in self.result.master_centers
            if c not in self.removed and c not in occupied
        ]

    def rebuild_scene(self) -> None:
        scene = self.scene
        scene.clear()
        self._tube_items.clear()
        self._component_items.clear()
        if self.result is None:
            return
        result = self.result
        pad = max(result.big_r_wai, 10.0) * 0.18
        scene.setSceneRect(
            -result.big_r_wai - pad, -result.big_r_wai - pad,
            (result.big_r_wai + pad) * 2, (result.big_r_wai + pad) * 2,
        )
        self._draw_axes(result.big_r_wai)
        self._draw_envelope(result)
        self._draw_partition(result)
        self._draw_tubes(result)
        self._draw_components()
        self._draw_center_lines(result)
        self.view.fit_all()
        self._update_lagan_summary()

    def _draw_axes(self, radius: float) -> None:
        extension = radius * 0.1
        total = radius + extension
        arrow = 10
        x_color = QColor(Qt.red)
        x_color.setAlpha(128)
        y_color = QColor(Qt.green)
        y_color.setAlpha(128)
        pen_x = QPen(x_color)
        pen_x.setWidth(5)
        pen_y = QPen(y_color)
        pen_y.setWidth(5)
        for item in (
            self.scene.addLine(-total, 0, total, 0, pen_x),
            self.scene.addLine(total, 0, total - arrow, -arrow / 2, pen_x),
            self.scene.addLine(total, 0, total - arrow, arrow / 2, pen_x),
            self.scene.addLine(-total, 0, -total + arrow, -arrow / 2, pen_x),
            self.scene.addLine(-total, 0, -total + arrow, arrow / 2, pen_x),
            self.scene.addLine(0, -total, 0, total, pen_y),
            self.scene.addLine(0, -total, -arrow / 2, -total + arrow, pen_y),
            self.scene.addLine(0, -total, arrow / 2, -total + arrow, pen_y),
            self.scene.addLine(0, total, -arrow / 2, total - arrow, pen_y),
            self.scene.addLine(0, total, arrow / 2, total - arrow, pen_y),
        ):
            item.setZValue(15)
        font = QFont("Arial", 11, QFont.Bold)
        for label, x, y in (
            ("0°", -10, -total - 46),
            ("90°", total + 8, -20),
            ("180°", -22, total + 6),
            ("270°", -total - 46, -20),
        ):
            text = self.scene.addText(label, font)
            text.setDefaultTextColor(QColor(90, 90, 90))
            text.setPos(x, y)
            text.setZValue(16)

    def _draw_envelope(self, result: engine.LayoutResult) -> None:
        pens = {
            "外圆": QPen(Qt.black, 2),
            "内圆": QPen(Qt.gray, 2),
            "限定圆": QPen(QColor(0, 0, 0), 2),
        }
        for key, pen in pens.items():
            radius = getattr(result, {"外圆": "big_r_wai", "内圆": "big_r_di", "限定圆": "big_r_nei"}[key])
            if radius <= 0:
                continue
            item = self.scene.addEllipse(-radius, -radius, radius * 2, radius * 2, pen, QBrush(Qt.NoBrush))
            item.setZValue(20)
        if result.baffle_r > 0:
            pen = QPen(QColor(120, 120, 120), 1.6, Qt.DashLine)
            item = self.scene.addEllipse(
                -result.baffle_r, -result.baffle_r, result.baffle_r * 2, result.baffle_r * 2,
                pen, QBrush(Qt.NoBrush),
            )
            item.setZValue(18)

    def _draw_partition(self, result: engine.LayoutResult) -> None:
        """分程隔板：按 SN（竖直）/SNH（水平）在管孔带之间画隔板带。"""
        do = result.small_r * 2
        radius = result.big_r_nei or result.big_r_wai
        sn = result.SN
        snh = float(result.raw.get("SNH") or 0)
        band_pen = QPen(QColor(80, 80, 80), 1.4)
        hatch = QBrush(QColor(200, 200, 200, 140), Qt.BDiagPattern)
        if sn and sn > do:
            half = (sn - do) / 2.0
            if half > 0.3 and half < radius:
                chord = math.sqrt(max(radius ** 2 - half ** 2, 0))
                rect = self.scene.addRect(-chord, -half, chord * 2, half * 2, band_pen, hatch)
                rect.setZValue(12)
        if snh and snh > do:
            half = (snh - do) / 2.0
            if half > 0.3 and half < radius:
                chord = math.sqrt(max(radius ** 2 - half ** 2, 0))
                rect = self.scene.addRect(-half, -chord, half * 2, chord * 2, band_pen, hatch)
                rect.setZValue(12)

    def _draw_tubes(self, result: engine.LayoutResult) -> None:
        r = result.small_r
        for center in self.current_centers():
            item = TubeItem(center, r, self)
            item.apply_selected(center in self.selected)
            self.scene.addItem(item)
            self._tube_items[center] = item

    def _draw_center_lines(self, result: engine.LayoutResult) -> None:
        """圆心连线：与正式程序 connect_center 一致——凡距离等于中心距 S 的相邻管孔连蓝色细线。

        正式程序用网格索引把 O(n²) 降到 O(n)，这里照搬；排列方式（转角三角形/正方形……）
        不同时相邻方向也不同，因此不能只判同行间距。
        """
        spacing = float(result.S or 0.0)
        if spacing <= 0:
            return
        centers = list(self.current_centers())
        if len(centers) < 2:
            return
        tolerance = max(1.0, spacing * 0.05)
        grid_size = max(spacing * 1.2, 1e-6)
        grid: dict[tuple[int, int], list[int]] = {}
        for index, (x, y) in enumerate(centers):
            grid.setdefault((round(x / grid_size), round(y / grid_size)), []).append(index)

        path = QPainterPath()
        linked: set[tuple[int, int]] = set()
        for index, (x0, y0) in enumerate(centers):
            cell = (round(x0 / grid_size), round(y0 / grid_size))
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for other in grid.get((cell[0] + dx, cell[1] + dy), ()):
                        if other <= index:
                            continue
                        pair = (index, other)
                        if pair in linked:
                            continue
                        x1, y1 = centers[other]
                        if abs(math.hypot(x1 - x0, y1 - y0) - spacing) <= tolerance:
                            linked.add(pair)
                            path.moveTo(x0, y0)
                            path.lineTo(x1, y1)
        if path.isEmpty():
            return
        # 半透明蓝：既能看到“圆心连线”，又不至于在孔数多时盖住管孔圆圈
        pen = QPen(QColor(0, 60, 235, 140))
        pen.setWidthF(0.9)
        pen.setCosmetic(True)
        item = QGraphicsPathItem(path)
        item.setPen(pen)
        # 连线画在管孔下面：网格退为背景参考线，管孔圆圈仍然清晰可辨
        item.setZValue(-1)
        self.scene.addItem(item)

    # ------------------------------------------------------ 元件绘制
    def _draw_components(self) -> None:
        for index, component in enumerate(self.components):
            kind = component["kind"]
            center = component.get("center")
            if kind in {"rod", "free_rod", "block_tube"} and center:
                radius = self.result.small_r if self.result else 12.5
                if kind == "rod":
                    item = RodItem(center, radius, self, free=False)
                elif kind == "free_rod":
                    item = RodItem(center, radius, self, free=True)
                else:
                    item = BlockTubeItem(center, radius, self)
                item.apply_selected(self.selected_component == index)
                item.component_index = index
                self.scene.addItem(item)
                self._component_items[index] = item
            elif kind in {"bypass", "center_baffle", "impingement", "impingement_folded", "slide", "screw_ring"} and center:
                width, height = component.get("size", (40.0, 8.0))
                color = {
                    "bypass": BYPASS_COLOR,
                    "center_baffle": CENTER_BAFFLE_COLOR,
                    "impingement": IMPINGE_COLOR,
                    "impingement_folded": IMPINGE_COLOR,
                    "slide": SLIDE_COLOR,
                    "screw_ring": QColor(150, 100, 40),
                }[kind]
                rect = QRectF(center[0] - width / 2, center[1] - height / 2, width, height)
                item = ComponentRectItem(rect, self, kind=kind, label=COMPONENT_LABEL[kind], color=color)
                item.apply_selected(self.selected_component == index)
                item.component_index = index
                self.scene.addItem(item)
                self._component_items[index] = item
            elif kind == "radial_hole" and center:
                path = self._radial_hole_path(center)
                if path is not None:
                    item = RadialHoleItem(path, self)
                    item.component_index = index
                    item.apply_selected(self.selected_component == index)
                    self.scene.addItem(item)
                    self._component_items[index] = item

    def _radial_hole_path(self, center) -> QPainterPath | None:
        if self.result is None:
            return None
        cx, cy = center
        length = math.hypot(cx, cy)
        if length < 1e-6:
            return None
        dx, dy = cx / length, cy / length
        nx, ny = -dy, dx
        r = self.result.small_r
        # 沿半径方向开口：以管孔中心为顶点，向外张开的楔形（正式程序径向开孔的简化几何）
        path = QPainterPath()
        path.moveTo(cx + nx * r, cy + ny * r)
        path.lineTo(cx + dx * r * 2.2, cy + dy * r * 2.2)
        path.lineTo(cx - nx * r, cy - ny * r)
        path.closeSubpath()
        return path

    # ------------------------------------------------------ 数量表同步
    def _groupings(self) -> None:
        if self.result is None:
            return
        master = self.result.master_centers
        centers = self.current_centers()
        self._rows_pos, self._rows_neg = geometry.group_centers_by_y(centers, master)
        self._cols_right, self._cols_left = geometry.group_centers_by_x(centers, master)

    def refresh_hole_table(self) -> None:
        if self.result is None:
            return
        self._groupings()
        if self.hole_table.by_row:
            first, second = self._rows_pos, self._rows_neg
        else:
            first, second = self._cols_right, self._cols_left
        self.hole_table.set_data(first, second, total=len(self.current_centers()))
        self.hole_table.set_selected_count(len(self.selected))
        # 表格重建后把“图形里仍选中的管孔”对应的行重新高亮
        self._sync_table_highlight()
        self.selection_label.setText(
            f"已选中 {len(self.selected)} 个管孔" if self.selected else "未选中管孔"
        )
        self.selected_count_changed.emit(len(self.selected))

    def on_table_rows_selected(self, rows: list[int]) -> None:
        if self.result is None:
            return
        if self.hole_table.by_row:
            first, second = self._rows_pos, self._rows_neg
        else:
            first, second = self._cols_right, self._cols_left
        centers: list[tuple[float, float]] = []
        for row in rows:
            if row < len(first):
                centers.extend(first[row])
            if row < len(second):
                centers.extend(second[row])
        self.select_centers(centers)
        if centers:
            self.status_message.emit(
                f"已选中{_describe_rows(rows)}，共 {len(self.selected)} 个换热管孔"
            )
        else:
            self.status_message.emit("已取消筛选，恢复显示全部管孔")

    def select_centers(self, centers: list[tuple[float, float]], additive: bool = False) -> None:
        if not additive:
            for center, item in self._tube_items.items():
                if item.is_selected:
                    item.apply_selected(False)
            self.selected.clear()
        for center in centers:
            if center in self._tube_items:
                self.selected.add(center)
                self._tube_items[center].apply_selected(True)
        self._sync_table_highlight()
        self.hole_table.set_selected_count(len(self.selected))
        self.selection_label.setText(
            f"已选中 {len(self.selected)} 个管孔" if self.selected else "未选中管孔"
        )
        self.selected_count_changed.emit(len(self.selected))

    def _sync_table_highlight(self) -> None:
        if not self.selected:
            self.hole_table.highlight_for_selection([])
            return
        if self.hole_table.by_row:
            first, second = self._rows_pos, self._rows_neg
        else:
            first, second = self._cols_right, self._cols_left
        rows: list[int] = []
        for index in range(max(len(first), len(second))):
            group = []
            if index < len(first):
                group.extend(first[index])
            if index < len(second):
                group.extend(second[index])
            if any(center in self.selected for center in group):
                rows.append(index)
        self.hole_table.highlight_for_selection(rows)

    # ------------------------------------------------------ 图形交互
    def item_clicked(self, item, modifiers) -> None:
        additive = bool(modifiers & (Qt.ControlModifier | Qt.ShiftModifier))
        if item.item_kind == "tube":
            center = item.center
            if center in self.selected:
                self.selected.discard(center)
                item.apply_selected(False)
            else:
                if not additive:
                    for other, other_item in self._tube_items.items():
                        if other_item.is_selected:
                            other_item.apply_selected(False)
                    self.selected.clear()
                self.selected.add(center)
                item.apply_selected(True)
            self._sync_table_highlight()
            self.hole_table.set_selected_count(len(self.selected))
            self.selection_label.setText(
                f"已选中 {len(self.selected)} 个管孔" if self.selected else "未选中管孔"
            )
            self.selected_count_changed.emit(len(self.selected))
            return
        index = getattr(item, "component_index", None)
        if index is not None:
            for other_index, other in self._component_items.items():
                other.apply_selected(other_index == index)
            self.selected_component = index
            label = COMPONENT_LABEL.get(self.components[index]["kind"], "元件")
            self.status_message.emit(f"已选中{label}，可点击“删除”移除")

    def on_rubber_band(self, rect: QRectF) -> None:
        picked = [
            center for center in self._tube_items
            if rect.contains(QPointF(center[0], center[1]))
        ]
        if not picked:
            return
        additive = bool(QApplication.keyboardModifiers() & Qt.ControlModifier)
        self.select_centers(picked, additive=additive)
        self.status_message.emit(f"框选到 {len(picked)} 个换热管孔，共选中 {len(self.selected)} 个")

    def clear_selection(self) -> None:
        """右键取消筛选：清掉表格选中行、图形选中与元件选中（正式程序同款）。"""
        had_selection = bool(self.selected) or self.selected_component is not None
        for item in self._tube_items.values():
            if item.is_selected:
                item.apply_selected(False)
        self.selected.clear()
        for index, item in self._component_items.items():
            item.apply_selected(False)
        self.selected_component = None
        self.hole_table.clear_selection()
        self.hole_table.highlight_for_selection([])
        self.hole_table.set_selected_count(0)
        self.selection_label.setText("未选中管孔")
        self.selected_count_changed.emit(0)
        self.status_message.emit(
            "已取消筛选，恢复显示全部管孔" if had_selection else "当前没有筛选/选中的管孔"
        )

    # ------------------------------------------------------ 元件操作
    def _require_selection(self) -> list[tuple[float, float]]:
        if not self.selected:
            self._warn("请先选择", "请先在图形中或右侧表格中选择换热管孔。", kind="info")
            return []
        return sorted(self.selected)

    def _push_undo(self) -> None:
        self._undo.append({
            "removed": set(self.removed),
            "components": deepcopy(self.components),
            "params": deepcopy(self.parameters),
        })
        if len(self._undo) > 30:
            self._undo.pop(0)

    def undo(self) -> None:
        if not self._undo:
            self.status_message.emit("没有可撤销的操作")
            return
        state = self._undo.pop()
        self.removed = set(state["removed"])
        self.components = deepcopy(state["components"])
        self.parameters = deepcopy(state["params"])
        self.selected.clear()
        self.selected_component = None
        self.rebuild_parameter_table()
        self.recompute(reason="已撤销上一步")
        self.status_message.emit("已撤销上一步操作")

    def _param_text(self, name: str) -> str:
        return str(self.parameters.get(name, {}).get("value", "") or "").strip()

    def _ask(self, title: str, fields: list[ParamField], hint: str = "") -> dict | None:
        """布置元件前弹窗确认参数（正式程序同款）；离屏自检时直接取当前值。"""
        values = {spec.name: self._param_text(spec.name) for spec in fields}
        if self.headless:
            return values
        return ask_component_params(title, fields, values, hint=hint, parent=self)

    def _write_back(self, values: dict) -> None:
        for name, value in values.items():
            if name in self.parameters and str(self.parameters[name].get("value", "")) != str(value):
                self.set_parameter(name, value, "人工修改", run_linkage=False)

    def place_rod(self, free: bool = False) -> None:
        centers = self._require_selection()
        if not centers:
            return
        fields = [
            ParamField("拉杆形式", "combo", ("焊接拉杆", "螺纹拉杆")),
            ParamField("拉杆直径", "combo", TIE_ROD_DIAMETERS),
        ]
        hint = (
            f"共选中 {len(centers)} 个管孔；拉杆直径决定拉杆图元与写库参数。"
            f"标准要求数量 {self._param_text('拉杆数量') or '-'}，"
            f"已有 {sum(1 for c in self.components if c['kind'] in {'rod', 'free_rod'})} 根。"
        )
        values = self._ask("拉杆参数设置", fields, hint)
        if values is None:
            return
        self._write_back(values)
        do = self._float("换热管外径 do") or 25.0
        rod_d = self._float("拉杆直径") or 16.0
        if rod_d > do + 1e-6:
            # 拉杆是占一个换热管孔位画的，直径不可能大于管孔
            self._warn(
                "拉杆直径无效",
                f"拉杆直径 {rod_d:g} 大于换热管外径 do={do:g}，无法穿入管孔。",
            )
            return
        self._push_undo()
        for center in centers:
            self.removed.add(center)
            self.components.append({"kind": "free_rod" if free else "rod", "center": center})
        self.selected.clear()
        self.rebuild_scene()
        self.refresh_hole_table()
        self.status_message.emit(
            f"已布置 {len(centers)} 根{'自由拉杆' if free else '拉杆'}，管孔数量已更新"
        )

    def place_block_tube(self) -> None:
        centers = self._require_selection()
        if not centers:
            return
        values = self._ask(
            "中间挡管参数设置",
            [ParamField("中间挡管安装方式", "combo", ("贯穿", "分割"))],
            f"共选中 {len(centers)} 个管孔。",
        )
        if values is None:
            return
        self._write_back(values)
        self._push_undo()
        for center in centers:
            self.removed.add(center)
            self.components.append({"kind": "block_tube", "center": center})
        self.selected.clear()
        self.rebuild_scene()
        self.refresh_hole_table()
        self.status_message.emit(f"已布置 {len(centers)} 个中间挡管")

    def place_plate(self, kind: str) -> None:
        centers = self._require_selection()
        if not centers:
            return
        if kind == "bypass":
            values = self._ask(
                "旁路挡板参数设置",
                [
                    ParamField("旁路挡板厚度", "number", unit="mm", minimum=0.1),
                    ParamField("旁路挡板宽度", "number", unit="mm", minimum=1.0),
                ],
            )
        else:
            values = self._ask(
                "中间挡板参数设置",
                [
                    ParamField("中间挡板厚度", "number", unit="mm", minimum=0.1),
                    ParamField("中间挡板宽度", "number", unit="mm", minimum=1.0),
                    ParamField("中间挡板安装方式", "combo", ("贯穿", "分割")),
                ],
            )
        if values is None:
            return
        self._write_back(values)
        if kind == "bypass":
            height = self._float("旁路挡板厚度") or 6.0
            width = max(self._float("旁路挡板宽度") or 40.0, 40.0)
        else:
            height = self._float("中间挡板厚度") or 6.0
            width = self._float("中间挡板宽度") or 60.0
        self._push_undo()
        for center in centers:
            # 挡板沿径向放置，朝向由所选管孔方位决定
            angle = math.degrees(math.atan2(-center[1], center[0])) if any(center) else 0.0
            self.components.append({
                "kind": kind, "center": center, "size": (width, height), "angle": angle,
            })
        self.selected.clear()
        self.rebuild_scene()
        self.status_message.emit(f"已布置 {len(centers)} 个{COMPONENT_LABEL[kind]}")

    def place_slide(self) -> None:
        centers = self._require_selection()
        if not centers:
            return
        is_kettle = self.product_type in {"AKU", "BKU"}

        def is_round(values: dict) -> bool:
            return values.get("滑道形式") == "圆钢滑道"

        def show_azimuth(values: dict) -> bool:
            return values.get("滑道形式") == "板式滑道" and values.get("滑道数量") == "1"

        fields = [
            ParamField("滑道定位", "combo", ("固定管板", "第一块折流板或支持板")),
            ParamField("滑道形式", "combo", ("板式滑道", "圆钢滑道")),
            ParamField("滑道数量", "combo", ("1", "2")),
            ParamField("滑道方位角", "number", unit="°", visible=show_azimuth),
            ParamField("导轨类型", "combo", ("支撑导轨1", "支撑导轨2"), visible=lambda _v: is_kettle),
            ParamField("圆钢规格", "number", unit="mm", minimum=0.1, visible=is_round),
            ParamField("滑道高度", "number", unit="mm", minimum=1.0,
                       visible=lambda v: not is_round(v)),
            ParamField("滑道厚度", "number", unit="mm", minimum=0.1,
                       visible=lambda v: not is_round(v)),
            ParamField("滑道与竖直中心线夹角", "number", unit="°",
                       visible=lambda v: is_round(v) or not show_azimuth(v)),
            ParamField("滑道切边长度", "number", unit="mm", minimum=0.0,
                       visible=lambda v: not is_round(v)),
            ParamField("滑道切边高度", "number", unit="mm", minimum=0.0,
                       visible=lambda v: not is_round(v)),
        ]
        values = self._ask("滑道参数设置", fields, f"共选中 {len(centers)} 个管孔。")
        if values is None:
            return
        self._write_back(values)
        height = self._float("滑道高度") or 150.0
        thickness = self._float("滑道厚度") or 10.0
        if is_round(values):
            thickness = self._float("圆钢规格") or thickness
        self._push_undo()
        for center in centers:
            self.components.append({
                "kind": "slide", "center": center, "size": (height, thickness), "angle": 0.0,
            })
        self.selected.clear()
        self.rebuild_scene()
        self.status_message.emit(f"已布置 {len(centers)} 条滑道")

    def place_impingement(self) -> None:
        centers = self._require_selection()
        if not centers:
            return

        def not_flat(values: dict) -> bool:
            return values.get("防冲板形式") != "平板形"

        def welded(values: dict) -> bool:
            return values.get("防冲板形式") == "焊接式"

        fields = [
            ParamField("防冲板形式", "combo", ("平板形", "圆弧形", "焊接式")),
            ParamField("防冲板厚度", "number", unit="mm", minimum=0.1),
            ParamField("防冲板折边角度", "number", unit="°", minimum=15, maximum=90,
                       visible=not_flat),
            ParamField("防冲板宽度", "number", unit="mm", minimum=1.0, visible=welded),
            ParamField("防冲板方位角", "number", unit="°", minimum=0, maximum=359.9,
                       visible=welded),
            ParamField("至圆筒内壁距离", "number", unit="mm", minimum=0.1, visible=welded),
        ]
        values = self._ask("防冲板参数设置", fields, f"共选中 {len(centers)} 个管孔。")
        if values is None:
            return
        self._write_back(values)
        width = self._float("防冲板宽度") or 200.0
        thickness = self._float("防冲板厚度") or 10.0
        kind = "impingement_folded" if values.get("防冲板形式") == "焊接式" else "impingement"
        self._push_undo()
        for center in centers:
            self.components.append({
                "kind": kind, "center": center, "size": (width, thickness),
                "angle": self._float("防冲板方位角") or 0.0,
            })
        self.selected.clear()
        self.rebuild_scene()
        self.status_message.emit(f"已布置 {len(centers)} 块防冲板")

    def place_screw_ring(self) -> None:
        values = self._ask(
            "吊环螺钉参数设置",
            [
                ParamField("吊环螺钉规格", "combo", ("M16", "M20", "M24", "M30", "M36")),
                ParamField("吊环螺钉数量", "number", unit="个", minimum=1, maximum=64),
                ParamField("吊环螺钉孔中心距", "number", unit="mm", minimum=0.0),
                ParamField("吊环螺钉起始方位角", "number", unit="°", minimum=0, maximum=359.9),
            ],
            "吊环螺钉沿管板外圆均布。",
        )
        if values is None:
            return
        self._write_back(values)
        quantity = int(self._float("吊环螺钉数量") or 4)
        start = self._float("吊环螺钉起始方位角") or 0.0
        radius = (self.result.big_r_wai if self.result else 500.0)
        self._push_undo()
        for index in range(quantity):
            angle = math.radians(start + index * (360.0 / max(quantity, 1)))
            center = (radius * math.cos(angle), radius * math.sin(angle))
            self.components.append({"kind": "screw_ring", "center": center, "size": (14.0, 14.0)})
        self.rebuild_scene()
        self.status_message.emit(f"已布置 {quantity} 个吊环螺钉")

    def place_baffle(self) -> None:
        if self.result is None:
            return

        def double_bow(values: dict) -> bool:
            return values.get("折流板类型") == "双弓形"

        fields = [
            ParamField("折流/支持板外径", "number", unit="mm", minimum=1.0),
            ParamField("折流/支持板间距", "number", unit="mm", minimum=1.0),
            ParamField("折流板类型", "combo", ("单弓形", "双弓形", "支持板")),
            ParamField("折流板切口方向", "combo", ("水平上下", "垂直左右")),
            ParamField("折流板要求切口率", "number", unit="%", minimum=10, maximum=45),
            ParamField("折流板切口与中心线间距a", "number", unit="mm", minimum=0.0),
            ParamField("弓形弦高切口率", "number", unit="%", minimum=0.0, maximum=100.0,
                       visible=double_bow),
            ParamField("内侧中心切口率", "number", unit="%", minimum=0.0, maximum=100.0,
                       visible=double_bow),
            ParamField("A型板切口与中心线间距a", "number", unit="mm", minimum=0.0,
                       visible=double_bow),
            ParamField("B型板切口与中心线间距b", "number", unit="mm", minimum=0.0,
                       visible=double_bow),
        ]
        values = self._ask(
            "折流板参数设置", fields,
            "折流/支持板外径与间距影响布管图中的折流板虚线圆和轴向设计页。",
        )
        if values is None:
            return
        self._write_back(values)
        self.recompute(reason="折流板参数已确认")
        spacing = self._float("折流/支持板间距") or 200.0
        self.status_message.emit(
            f"折流板已按 折流/支持板外径 {self.result.baffle_r * 2:g}、间距 {spacing:g} 绘制（虚线圆），"
            "布置数量由 轴向设计 页确认"
        )

    def place_radial_hole(self) -> None:
        centers = self._require_selection()
        if not centers:
            return
        self._push_undo()
        for center in centers:
            self.components.append({"kind": "radial_hole", "center": center})
        self.selected.clear()
        self.rebuild_scene()
        self.status_message.emit(f"已在 {len(centers)} 个管孔位置开径向孔")

    def restore_tubes(self) -> None:
        if not self.removed:
            self.status_message.emit("当前没有被删除的管孔")
            return
        self._push_undo()
        restored = len(self.removed)
        self.removed.clear()
        self.components = [
            c for c in self.components
            if c["kind"] not in {"rod", "free_rod", "block_tube"}
        ]
        self.rebuild_scene()
        self.refresh_hole_table()
        self.status_message.emit(f"已恢复 {restored} 个换热管孔")

    def delete_selected(self) -> None:
        if self.selected:
            self._push_undo()
            count = len(self.selected)
            self.removed |= set(self.selected)
            self.selected.clear()
            self.rebuild_scene()
            self.refresh_hole_table()
            self.status_message.emit(f"已删除 {count} 个换热管孔，管孔数量已刷新")
            return
        if self.selected_component is not None:
            self._push_undo()
            component = self.components.pop(self.selected_component)
            if component["kind"] in {"rod", "free_rod", "block_tube"} and component.get("center"):
                self.removed.discard(component["center"])
            self.selected_component = None
            self.rebuild_scene()
            self.refresh_hole_table()
            self.status_message.emit(f"已删除{COMPONENT_LABEL.get(component['kind'], '元件')}")
            return
        self.status_message.emit("请先选择要删除的管孔或元件")

    def toggle_fullscreen(self) -> None:
        window = self.window()
        if window.isFullScreen():
            window.showNormal()
        else:
            window.showFullScreen()
        self.view.fit_all()

    # ------------------------------------------------------ 校验与摘要
    def show_issues(self) -> None:
        for row, name in enumerate(PARAM_ORDER):
            self._paint_param_row(row, name)
        self._clear_recommendations()
        if not self.issues:
            self.issue_frame.hide()
            self.keep_button.setEnabled(True)
            return
        lines = []
        for issue in self.issues:
            text = f"• {issue['field']}：{issue['message']}"
            if issue.get("recommended") is not None:
                text += f"（推荐 {issue['recommended']}）"
            lines.append(text)
        self.issue_list.setText("\n".join(lines))
        self.issue_title.setText(f"需要修改 · {len(self.issues)} 项")
        for issue in self.issues:
            if issue.get("recommended") is None:
                continue
            button = QPushButton(f"{issue['field']} 采用 {issue['recommended']}")
            button.setCursor(Qt.PointingHandCursor)
            button.setStyleSheet(
                "QPushButton{background:#fff;border:1px solid #e0b4b0;border-radius:6px;"
                "padding:4px 10px;color:#9b2c2c;font-size:9pt;}"
                "QPushButton:hover{background:#fff0ee;}"
            )
            button.clicked.connect(
                lambda _checked=False, field=issue["field"], value=issue["recommended"]: self.apply_recommendation(field, value)
            )
            self.recommend_box.addWidget(button)
        self.issue_frame.show()
        self.keep_button.setEnabled(False)

    def _clear_recommendations(self) -> None:
        """清掉上一次的“采用推荐值”按钮，避免重复累积。"""
        for index in reversed(range(self.recommend_box.count())):
            item = self.recommend_box.itemAt(index)
            widget = item.widget() if item is not None else None
            if widget is not None:
                self.recommend_box.takeAt(index)
                widget.setParent(None)
                widget.deleteLater()

    def apply_recommendation(self, field: str, value) -> None:
        if field not in self.parameters:
            return
        self.set_parameter(field, str(value), "采用推荐值")
        self.recompute(reason=f"已采用 {field} 推荐值 {value}")

    def _update_lagan_summary(self) -> None:
        rods = sum(1 for c in self.components if c["kind"] in {"rod", "free_rod"})
        required = self._float("拉杆数量") or 0
        self.lagan_summary.setText(
            f"拉杆标准要求数量{int(required) if required else '-'}  已有数量{rods}"
        )

    # ------------------------------------------------------ 对外数据
    def validation_issues(self) -> list[dict]:
        return list(self.issues)

    def to_payload(self) -> dict:
        components: dict[int, list] = {kind: [] for kind in range(11)}
        for component in self.components:
            kind = component["kind"]
            if kind == "radial_hole":
                continue
            component_type = COMPONENT_KIND_TO_TYPE.get(kind)
            if component_type is None:
                continue
            center = component.get("center")
            if center:
                coord = (round(center[0], 6), round(center[1], 6))
                if coord not in components[component_type]:
                    components[component_type].append(coord)
        components[7] = [(round(x, 6), round(y, 6)) for x, y in sorted(self.removed)]
        quantity_rows = []
        if self.result is not None:
            self._groupings()
            first, second = self._rows_pos, self._rows_neg
            for index in range(max(len(first), len(second))):
                rows_a = len(first[index]) if index < len(first) else 0
                rows_b = len(second[index]) if index < len(second) else 0
                quantity_rows.append({"idx": index + 1, "a": rows_a, "b": rows_b, "r": ""})
        return {
            "parameters": deepcopy(self.parameters),
            "components": components,
            "input": dict(self.result.input_json) if self.result else {},
            "result": {k: str(v) for k, v in (self.result.summary if self.result else {}).items()},
            "quantity_rows": quantity_rows,
            "quantity_vertical": not (self.product_type in {"AEU", "BEU", "AKU", "BKU"}
                                      and str(self.parameters["管程程数"]["value"]) == "2"),
            "hole_count": len(self.current_centers()),
            "selected_count": len(self.selected),
        }

    def summary_lines(self) -> list[str]:
        if self.result is None:
            return ["尚未布管"]
        lines = [
            f"管孔总数 {len(self.current_centers())} 个（正式程序布管接口计算）",
            f"换热管中心距 S {self.result.S:g}，分程隔板相邻管中心距 SN {self.result.SN:g}",
            f"布管限定圆 DL {self.result.big_r_nei * 2:g}，折流/支持板外径 {self.result.baffle_r * 2:g}",
            f"已有拉杆 {sum(1 for c in self.components if c['kind'] in {'rod', 'free_rod'})} 根，"
            f"其他元件 {sum(1 for c in self.components if c['kind'] not in {'rod', 'free_rod'})} 个",
        ]
        if self.removed:
            lines.append(f"已删除/被元件占用的管孔 {len(self.removed)} 个")
        return lines

    # ------------------------------------------------------ Agent 可调用的受控操作
    def run_validation(self) -> list[dict]:
        """统一入口：几何 + 参数一致性校验，并刷新标红与推荐值。"""
        issues = engine.check_geometry(self.parameters, self.result)
        self.issues = issues
        self.show_issues()
        return list(issues)

    def max_tubes(self, target: int | None = None) -> dict:
        """尽量多布：按正式程序中心距依次尝试更小的 S，直到满足目标或达到极限。"""
        current_s = self._float("换热管中心距 S") or 32.0
        do = self._float("换热管外径 do") or 25.0
        original = self.parameters["换热管中心距 S"]["value"]
        best = None
        s = current_s
        while s > do + 1.5:
            self.set_parameter("换热管中心距 S", self._pretty(s), "AI 建议", run_linkage=False)
            try:
                result = engine.compute(self.parameters, self.product_type, self.defaults)
            except Exception:  # noqa: BLE001 - 试算失败换下一个中心距
                s -= 1.0
                continue
            issues = engine.check_geometry(self.parameters, result)
            if not issues:
                best = (s, len(result.master_centers))
                if target is None or best[1] >= target:
                    break
            s -= 1.0
        if best is None:
            self.set_parameter("换热管中心距 S", original, "AI 建议", run_linkage=False)
            return {"ok": False, "message": "当前参数下无法排布更多换热管"}
        self.set_parameter("换热管中心距 S", self._pretty(best[0]), "AI 建议", run_linkage=False)
        self.recompute(reason="尽量多布")
        return {"ok": True, "S": best[0], "count": best[1]}

    def place_edge_rods(self, count: int) -> int:
        """外围对称布置拉杆：取上下最外两行 + 每行首尾管孔，成对生成。"""
        if self.result is None:
            return 0
        self._groupings()
        rows = [row for row in self._rows_pos if row] + [row for row in self._rows_neg if row]
        if not rows:
            return 0
        candidates: list[tuple[float, float]] = []
        top = max(rows, key=lambda r: r[0][1])
        bottom = min(rows, key=lambda r: r[0][1])
        for row in rows:
            if row is top or row is bottom:
                candidates.extend(row)
            else:
                candidates.append(row[0])
                candidates.append(row[-1])
        # 对称：按 x 排序后从左到右、从右到左交替，保证成对
        candidates = sorted(set(candidates), key=lambda p: (p[0], p[1]))
        picked: list[tuple[float, float]] = []
        left, right = 0, len(candidates) - 1
        while len(picked) < count and left <= right:
            picked.append(candidates[left])
            if len(picked) < count and left != right:
                picked.append(candidates[right])
            left += 1
            right -= 1
        if not picked:
            return 0
        self._push_undo()
        for center in picked:
            self.removed.add(center)
            self.components.append({"kind": "rod", "center": center})
        self.selected.clear()
        self.rebuild_scene()
        self.refresh_hole_table()
        return len(picked)

    def place_bypasses(self, count: int) -> int:
        """沿壳体内壁均布旁路挡板。"""
        if self.result is None or count <= 0:
            return 0
        width = self._float("旁路挡板宽度") or 40.0
        height = self._float("旁路挡板厚度") or 6.0
        radius = max(self.result.big_r_di - height / 2, 10.0)
        self._push_undo()
        added = 0
        for index in range(count):
            angle = math.radians(90.0 + index * (360.0 / max(count, 1)))
            center = (radius * math.cos(angle), radius * math.sin(angle))
            self.components.append({
                "kind": "bypass", "center": center, "size": (width, height), "angle": 0.0,
            })
            added += 1
        self.rebuild_scene()
        return added

    def place_impingement_top(self, count: int = 1) -> int:
        """在上方（+Y）布置防冲板。"""
        if self.result is None:
            return 0
        width = self._float("防冲板宽度") or 200.0
        thickness = self._float("防冲板厚度") or 10.0
        kind = "impingement_folded" if str(self.parameters["防冲板形式"]["value"]) == "焊接式" else "impingement"
        radius = max(self.result.big_r_di - thickness / 2 - 1, 10.0)
        self._push_undo()
        added = 0
        for index in range(max(count, 1)):
            offset = (index - (count - 1) / 2) * (width * 0.35)
            center = (offset, radius)
            self.components.append({
                "kind": kind, "center": center, "size": (width, thickness), "angle": 90.0,
            })
            added += 1
        self.rebuild_scene()
        return added
