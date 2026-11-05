"""布管页复用的小部件：带示意图的分程形式下拉框、元件参数确认弹窗。

两件东西都对标正式程序：
- `TubePassFormComboBox` 对应 My_Piping.TubePassFormComboBox：闭合态直接把
  `static/TubePattern/<标识>.png` 按单元格大小等比缩放绘制，不再显示 "2.1"
  这样的数字；展开后下拉项同样是示意图（比正式程序放得更大，便于辨认）。
- `ComponentParamDialog` 对应正式程序各元件的“××参数设置”弹窗：左侧参数表里
  隐藏的元件参数（滑道/防冲板/中间挡板/吊环螺钉/旁路挡板/拉杆…）在布置元件时
  由弹窗让用户确认，确认后才写回参数表并落图。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PyQt5.QtCore import QSize, Qt
from PyQt5.QtGui import QIcon, QPainter, QPixmap
from PyQt5.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QMessageBox,
    QPushButton,
    QStyle,
    QStyleOptionComboBox,
    QVBoxLayout,
    QWidget,
)


class TubePassFormComboBox(QComboBox):
    """管程分程形式：闭合态自绘示意图，下拉列表按大图显示。"""

    PIXMAP_ROLE = Qt.UserRole + 200
    POPUP_WIDTH = 460

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditable(False)
        self.setMinimumHeight(28)
        view = QListView()
        view.setSpacing(2)
        view.setStyleSheet("QListView::item{padding:2px 4px;}")
        self.setView(view)
        self.setStyleSheet(
            "QComboBox{border:1px solid #e6e5e2;border-radius:4px;background:#ffffff;"
            "padding:0px;padding-right:18px;}"
            "QComboBox:hover{border-color:#c9d8ea;}"
            "QComboBox::drop-down{subcontrol-origin:padding;subcontrol-position:top right;"
            "width:18px;border:none;background:transparent;}"
        )

    # ---- 绘制 ----
    def _preview_rect(self):
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        field_rect = self.style().subControlRect(
            QStyle.CC_ComboBox, option, QStyle.SC_ComboBoxEditField, self
        )
        return field_rect.adjusted(2, 2, -2, -2)

    def _current_pixmap(self) -> QPixmap | None:
        index = self.currentIndex()
        if index < 0:
            return None
        pixmap = self.itemData(index, self.PIXMAP_ROLE)
        if isinstance(pixmap, QPixmap) and not pixmap.isNull():
            return pixmap
        icon = self.itemIcon(index)
        if icon.isNull():
            return None
        sizes = icon.availableSizes()
        return icon.pixmap(sizes[0]) if sizes else icon.pixmap(QSize(460, 104))

    def paintEvent(self, event):  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        option.currentText = ""
        option.currentIcon = QIcon()
        self.style().drawComplexControl(QStyle.CC_ComboBox, option, painter, self)
        pixmap = self._current_pixmap()
        if pixmap is None:
            return
        target = self._preview_rect()
        if target.width() <= 0 or target.height() <= 0:
            return
        scaled = pixmap.scaled(target.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        painter.drawPixmap(
            target.x(), target.y() + (target.height() - scaled.height()) // 2, scaled
        )

    # ---- 弹窗大图 ----
    def _refresh_popup_icons(self) -> None:
        icon_size = QSize(self.POPUP_WIDTH, 60)
        for index in range(self.count()):
            pixmap = self.itemData(index, self.PIXMAP_ROLE)
            if not isinstance(pixmap, QPixmap) or pixmap.isNull():
                continue
            height = max(int(self.POPUP_WIDTH * pixmap.height() / max(pixmap.width(), 1)), 20)
            scaled = pixmap.scaled(
                QSize(self.POPUP_WIDTH, height), Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            self.setItemIcon(index, QIcon(scaled))
            icon_size = scaled.size()
        view = self.view()
        if view is not None:
            view.setIconSize(icon_size)
            view.setMinimumWidth(icon_size.width() + 16)
            view.setGridSize(QSize(icon_size.width() + 10, icon_size.height() + 8))

    def showPopup(self):  # noqa: N802 - Qt API
        self._refresh_popup_icons()
        super().showPopup()


@dataclass
class ParamField:
    """弹窗中的一个参数行。"""

    name: str
    kind: str = "number"                 # number / combo / readonly
    options: tuple[str, ...] = ()
    unit: str = ""
    minimum: float | None = None
    maximum: float | None = None
    visible: Callable[[dict], bool] | None = None
    tip: str = ""


class ComponentParamDialog(QDialog):
    """布置元件前的参数确认弹窗（正式程序同名弹窗的等价实现）。"""

    def __init__(self, title: str, fields: list[ParamField], values: dict,
                 hint: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(400)
        self.setStyleSheet("QDialog{background:#ffffff;}")
        self._fields = fields
        self._editors: dict[str, QWidget] = {}
        self._rows: dict[str, QWidget] = {}
        self._labels: dict[str, QWidget] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 12)
        root.setSpacing(10)
        if hint:
            hint_label = QLabel(hint)
            hint_label.setWordWrap(True)
            hint_label.setStyleSheet("color:#8f949c;font-size:9pt;")
            root.addWidget(hint_label)

        form_host = QWidget()
        form = QFormLayout(form_host)
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(8)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        for spec in fields:
            container = QWidget()
            row = QHBoxLayout(container)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(6)
            value = "" if values.get(spec.name) is None else str(values.get(spec.name))
            if spec.kind == "combo":
                editor = QComboBox()
                editor.setEditable(False)
                editor.addItems(list(spec.options))
                index = editor.findText(value)
                editor.setCurrentIndex(index if index >= 0 else 0)
            else:
                editor = QLineEdit(value)
                editor.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if spec.kind == "readonly":
                    editor.setReadOnly(True)
                    editor.setStyleSheet(
                        "QLineEdit{background:#f4f6f8;color:#6b7280;"
                        "border:1px solid #eef0f3;border-radius:4px;padding:3px 6px;}"
                    )
            editor.setStyleSheet(
                editor.styleSheet()
                or "QLineEdit{background:#fff;border:1px solid #e6e5e2;border-radius:4px;padding:3px 6px;}"
            )
            row.addWidget(editor, 1)
            if spec.unit:
                unit = QLabel(spec.unit)
                unit.setStyleSheet("color:#8f949c;")
                row.addWidget(unit)
            if spec.tip:
                container.setToolTip(spec.tip)
            self._editors[spec.name] = editor
            self._rows[spec.name] = container
            label = QLabel(f"{spec.name}：")
            self._labels[spec.name] = label
            form.addRow(label, container)
        root.addWidget(form_host)

        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton("取消")
        confirm = QPushButton("确定")
        confirm.setDefault(True)
        for button in (cancel, confirm):
            button.setCursor(Qt.PointingHandCursor)
            button.setMinimumWidth(80)
            button.setStyleSheet(
                "QPushButton{background:#fff;border:1px solid #dcdde0;border-radius:7px;padding:6px 16px;}"
                "QPushButton:hover{background:#f5f7fa;}"
            )
        confirm.setStyleSheet(
            "QPushButton{background:#2f6fe4;color:#fff;border:none;border-radius:7px;padding:6px 18px;}"
            "QPushButton:hover{background:#2a63cc;}"
        )
        cancel.clicked.connect(self.reject)
        confirm.clicked.connect(self._on_confirm)
        buttons.addWidget(cancel)
        buttons.addWidget(confirm)
        root.addLayout(buttons)

        for spec in fields:
            editor = self._editors[spec.name]
            if isinstance(editor, QComboBox):
                editor.currentIndexChanged.connect(self._apply_visibility)
        self._apply_visibility()

    # ---- 显隐 / 校验 ----
    def _values_now(self) -> dict:
        result = {}
        for name, editor in self._editors.items():
            if isinstance(editor, QComboBox):
                result[name] = editor.currentText().strip()
            elif isinstance(editor, QLineEdit):
                result[name] = editor.text().strip()
        return result

    def _apply_visibility(self) -> None:
        current = self._values_now()
        for spec in self._fields:
            container = self._rows.get(spec.name)
            if container is None or spec.visible is None:
                continue
            visible = bool(spec.visible(current))
            container.setVisible(visible)
            label = self._labels.get(spec.name)
            if label is not None:
                label.setVisible(visible)
        self.adjustSize()

    def values(self) -> dict:
        return self._values_now()

    def _on_confirm(self) -> None:
        values = self._values_now()
        for spec in self._fields:
            if spec.kind != "number":
                continue
            if not self._rows[spec.name].isVisible():
                continue
            text = values.get(spec.name, "")
            if text == "":
                QMessageBox.warning(self, "输入错误", f"“{spec.name}”不能为空。")
                return
            try:
                number = float(text)
            except ValueError:
                QMessageBox.warning(self, "输入错误", f"“{spec.name}”必须填写数字。")
                return
            if spec.minimum is not None and number < spec.minimum:
                QMessageBox.warning(
                    self, "输入错误", f"“{spec.name}”不能小于 {spec.minimum:g}。"
                )
                return
            if spec.maximum is not None and number > spec.maximum:
                QMessageBox.warning(
                    self, "输入错误", f"“{spec.name}”不能大于 {spec.maximum:g}。"
                )
                return
        self.accept()


def ask_component_params(title: str, fields: list[ParamField], values: dict,
                         hint: str = "", parent=None) -> dict | None:
    """弹窗取参数；用户取消返回 None。"""
    dialog = ComponentParamDialog(title, fields, values, hint=hint, parent=parent)
    if dialog.exec_() != QDialog.Accepted:
        return None
    return dialog.values()
