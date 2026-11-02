"""Demo-local copies of the stable parameter editor rules used by DongLanpec.

The production project is intentionally not imported here.  Its pages have database,
graphics and parent-window dependencies that do not belong in the independent demo.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QIntValidator, QPainter, QPen
from PyQt5.QtWidgets import (
    QComboBox,
    QLineEdit,
    QStyle,
    QStyledItemDelegate,
)


@dataclass(frozen=True)
class EditorSpec:
    options: tuple[str, ...]
    editable: bool = False


STANDARD_TUBE_LENGTHS = (
    "1000", "1500", "2000", "2500", "3000", "4500",
    "6000", "7500", "8000", "9000", "12000",
)
STANDARD_TUBE_DIAMETERS = (
    "10", "12", "14", "16", "19", "20", "22", "25",
    "30", "32", "35", "38", "45", "50", "55", "57",
)
STANDARD_TIE_ROD_DIAMETERS = (
    "10", "12", "14", "16", "19", "20", "25", "27",
    "30", "32", "35", "38", "45", "50", "55", "57",
)
TUBE_SHEET_CONNECTIONS = (
    "强度焊接加贴胀管孔结构",
    "机械胀接管孔结构",
    "强度焊接的焊缝形式",
    "机械强度胀接加密封焊管孔结构",
    "内孔焊接头形式",
)


class NoWheelComboBox(QComboBox):
    """Matches the production control: scrolling a table must not change a value."""

    def wheelEvent(self, event):  # noqa: N802 - Qt API
        event.ignore()


def _plain_number(value) -> str:
    text = "" if value is None else str(value).strip()
    try:
        number = float(text)
    except (TypeError, ValueError):
        return text
    return f"{number:g}"


def _tube_pass_options(product_type: str) -> tuple[str, ...]:
    product = str(product_type or "").strip().upper()
    if product in {"AEU", "BEU", "AKU", "BKU", "AES", "BES"}:
        return ("2", "4", "6", "8", "10", "12")
    return ("1", "2", "4", "6", "8", "10", "12")


def _tube_pass_form_options(pass_count) -> tuple[str, ...]:
    """Text equivalents of the production image choices for this lightweight demo."""
    count = _plain_number(pass_count)
    return {
        "1": ("1程-不分程",),
        "2": ("2程-水平分程", "2程-垂直分程"),
        "4": ("4.1", "4.2.1", "4.2.2", "4.3.1", "4.3.2"),
        "6": ("6.1.1", "6.1.2", "6.2.1", "6.2.2"),
        "8": ("8a.1", "8a.2", "8b.1", "8b.2", "8c.1", "8c.2", "8d.1", "8d.2"),
        "10": ("10a.1", "10a.2", "10b.1", "10b.2"),
        "12": ("12a.1", "12a.2", "12b.1", "12b.2"),
    }.get(count, ("未选择",))


def editor_spec(field: str, parameters, product_type: str = "") -> Optional[EditorSpec]:
    """Return the source-compatible editor for one preview parameter."""
    if field == "管板类型":
        # sheet_form_page.py uses the same a-f choices for AEU/BEU.
        return EditorSpec(tuple("abcdef"))
    if field == "管程程数":
        return EditorSpec(_tube_pass_options(product_type))
    if field == "管程分程形式":
        passes = parameters.get("管程程数", {}).get("value", "")
        return EditorSpec(_tube_pass_form_options(passes))
    if field == "换热管布置方式":
        return EditorSpec(("对中", "跨中", "任意"))
    if field == "换热管外径 do":
        return EditorSpec(STANDARD_TUBE_DIAMETERS, editable=True)
    if field == "换热管公称长度 LN":
        return EditorSpec(STANDARD_TUBE_LENGTHS, editable=True)
    if field == "拉杆直径":
        return EditorSpec(STANDARD_TIE_ROD_DIAMETERS)
    if field == "管板连接方式":
        return EditorSpec(TUBE_SHEET_CONNECTIONS)
    if field == "焊接结构形式":
        return EditorSpec(("a", "b", "c", "d", "e"))
    return None


def build_combo(spec: EditorSpec, value, on_commit: Callable[[str], None], parent=None) -> NoWheelComboBox:
    combo = NoWheelComboBox(parent)
    combo.setEditable(spec.editable)
    combo.addItems(list(spec.options))
    current = _plain_number(value)
    if current and combo.findText(current) < 0:
        if spec.editable:
            combo.setEditText(current)
        else:
            combo.addItem(current)
            combo.setCurrentText(current)
    elif current:
        combo.setCurrentText(current)
    elif combo.count():
        combo.setCurrentIndex(0)

    if spec.editable:
        combo.setValidator(QIntValidator(1, 99999, combo))
        combo.lineEdit().editingFinished.connect(lambda c=combo: on_commit(c.currentText().strip()))
    combo.activated[str].connect(on_commit)
    return combo


class ParamValueDelegate(QStyledItemDelegate):
    """Production-style value cell with an opaque editor (prevents text ghosting)."""

    def paint(self, painter, option, index):
        table = option.widget
        if table is not None and table.cellWidget(index.row(), index.column()) is not None:
            return
        painter.save()
        if option.state & QStyle.State_Selected:
            painter.fillRect(option.rect, option.palette.highlight())
        box = option.rect.adjusted(5, 4, -5, -4)
        editable = bool(index.flags() & Qt.ItemIsEditable)
        painter.setBrush(QColor("#ffffff" if editable else "#f5f6f7"))
        painter.setPen(QPen(QColor("#cccccc"), 1))
        painter.drawRect(box)
        painter.setPen(QColor("#303133" if editable else "#8b8d91"))
        text = "" if index.data(Qt.DisplayRole) is None else str(index.data(Qt.DisplayRole))
        painter.drawText(box.adjusted(9, 0, -8, 0), Qt.AlignLeft | Qt.AlignVCenter, text)
        painter.restore()

    def createEditor(self, parent, option, index):
        editor = QLineEdit(parent)
        editor.setFrame(False)
        editor.setStyleSheet(
            "QLineEdit{background:#ffffff;color:#202124;border:1px solid #b8c4d2;"
            "padding:2px 9px;font-family:'Microsoft YaHei UI';font-size:10pt;}"
            "QLineEdit:focus{border:1px solid #6f98c8;}"
        )
        return editor

    def setEditorData(self, editor, index):
        editor.setText("" if index.data(Qt.DisplayRole) is None else str(index.data(Qt.DisplayRole)))
        editor.selectAll()

    def setModelData(self, editor, model, index):
        model.setData(index, editor.text().strip(), Qt.EditRole)

    def updateEditorGeometry(self, editor, option, index):
        editor.setGeometry(option.rect.adjusted(5, 4, -5, -4))


_ARROW_URL = (Path(__file__).resolve().parent / "assets" / "combo_arrow_gray.svg").as_posix()

COMBO_STYLE = """
QComboBox {
    background:#ffffff;
    color:#202124;
    border:1px solid #cccccc;
    padding:2px 24px 2px 8px;
    font-family:'Microsoft YaHei UI';
    font-size:10pt;
    min-height:26px;
}
QComboBox:hover, QComboBox:focus { border-color:#8ba9c8; }
QComboBox::drop-down { width:22px; border:none; background:transparent; }
QComboBox::down-arrow { image:url(__ARROW_URL__); width:10px; height:6px; }
QComboBox QAbstractItemView {
    background:#ffffff;
    color:#202124;
    border:1px solid #cccccc;
    selection-background-color:#d9e6f7;
    selection-color:#202124;
    outline:0;
}
QComboBox QLineEdit {
    background:#ffffff;
    color:#202124;
    border:none;
    padding:0;
    selection-background-color:#d9e6f7;
}
""".replace("__ARROW_URL__", _ARROW_URL)


def style_combo(combo: QComboBox) -> None:
    combo.setStyleSheet(COMBO_STYLE)
    combo.setMinimumHeight(34)

