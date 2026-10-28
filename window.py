from __future__ import annotations

import html
from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QFont
from PyQt5.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QDoubleSpinBox, QFileDialog, QFrame,
    QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPlainTextEdit, QPushButton,
    QScrollArea, QSizePolicy, QSplitter, QTableWidget, QTableWidgetItem, QTextBrowser,
    QVBoxLayout, QWidget,
)

from ai_support.api_client import DeepSeekClient
from demo_db import DemoRepository
from document_reader import DocumentBundle, identify_equipment, scan_inputs
from models import STAGES
from pipeline import TubeBundleAgent
from review_session import ReviewSession
from settings import load_settings, settings_dialog


EXAMPLE_ZIP = Path(__file__).resolve().parent.parent / "01-管壳式热交换器-输入文件 (2).zip"


class DesignWindow(QMainWindow):
    def __init__(self, repository=None):
        super().__init__()
        self.repository = repository or DemoRepository()
        self._owns_repository = repository is None
        self.config = load_settings()
        self.bundle = DocumentBundle([])
        self.selected_paths = []
        self.session = None
        self.prepared = None
        self._updating_table = False
        self.recommendation_buttons = []
        self.setWindowTitle("管束 AI 审核助手 Demo")
        self.resize(1540, 920)
        self.setMinimumSize(1180, 720)
        self._build_ui()
        self._apply_style()
        self.append_chat("assistant", "请先选择输入文件，或点击“使用示例输入包”。我会先识别设备，再准备四个管束审核阶段。")

    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(10)

        header = QHBoxLayout()
        title = QLabel("管束 AI 审核助手")
        title.setObjectName("mainTitle")
        header.addWidget(title)
        header.addStretch()
        self.db_label = QLabel("独立演示数据库")
        self.db_label.setObjectName("safeBadge")
        header.addWidget(self.db_label)
        settings_button = QPushButton("DeepSeek 设置")
        settings_button.clicked.connect(self.open_settings)
        header.addWidget(settings_button)
        layout.addLayout(header)

        self.progress_layout = QHBoxLayout()
        self.progress_labels = []
        for index, text in enumerate(("文件", "设备确认", *STAGES, "完成")):
            label = QLabel(f"{index + 1}  {text}")
            label.setObjectName("progressIdle")
            label.setAlignment(Qt.AlignCenter)
            self.progress_labels.append(label)
            self.progress_layout.addWidget(label)
        layout.addLayout(self.progress_layout)

        source = QFrame()
        source.setObjectName("sourceBar")
        source_layout = QHBoxLayout(source)
        choose = QPushButton("选择输入文件")
        choose.clicked.connect(self.select_files)
        source_layout.addWidget(choose)
        example = QPushButton("使用示例输入包")
        example.clicked.connect(self.use_example_package)
        source_layout.addWidget(example)
        self.file_label = QLabel("尚未选择文件")
        self.file_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        source_layout.addWidget(self.file_label)
        source_layout.addWidget(QLabel("设备位号"))
        self.equipment_combo = QComboBox()
        self.equipment_combo.setEditable(True)
        self.equipment_combo.setMinimumWidth(190)
        source_layout.addWidget(self.equipment_combo)
        source_layout.addWidget(QLabel("产品型式"))
        self.product_combo = QComboBox()
        self.product_combo.addItems(("AEU", "BEU", "AKU", "BKU", "AES", "BES", "AEM", "BEM", "NEN", "NEN(H)"))
        source_layout.addWidget(self.product_combo)
        source_layout.addWidget(QLabel("DN"))
        self.dn = QDoubleSpinBox()
        self.dn.setRange(100, 5000)
        self.dn.setValue(700)
        self.dn.setSuffix(" mm")
        source_layout.addWidget(self.dn)
        start = QPushButton("开始处理")
        start.setObjectName("primaryButton")
        start.clicked.connect(self.start_analysis)
        source_layout.addWidget(start)
        layout.addWidget(source)

        splitter = QSplitter(Qt.Horizontal)
        layout.addWidget(splitter, 1)

        chat_panel = QFrame()
        chat_panel.setObjectName("panel")
        chat_layout = QVBoxLayout(chat_panel)
        chat_header = QLabel("AI 执行记录与对话")
        chat_header.setObjectName("sectionTitle")
        chat_layout.addWidget(chat_header)
        self.conversation = QTextBrowser()
        self.conversation.setOpenExternalLinks(False)
        chat_layout.addWidget(self.conversation, 1)
        self.prompt = QPlainTextEdit()
        self.prompt.setPlaceholderText("可在这里记录补充要求或修改原因……")
        self.prompt.setMaximumHeight(90)
        chat_layout.addWidget(self.prompt)
        send = QPushButton("发送备注")
        send.clicked.connect(self.send_note)
        chat_layout.addWidget(send, alignment=Qt.AlignRight)
        splitter.addWidget(chat_panel)

        review_panel = QFrame()
        review_panel.setObjectName("panel")
        review_layout = QVBoxLayout(review_panel)
        top = QHBoxLayout()
        self.stage_title = QLabel("尚未开始审核")
        self.stage_title.setObjectName("sectionTitle")
        top.addWidget(self.stage_title)
        top.addStretch()
        self.review_status = QLabel("等待文件")
        self.review_status.setObjectName("statusBadge")
        top.addWidget(self.review_status)
        review_layout.addLayout(top)
        self.stage_hint = QLabel("AI 会给出基础值、文件候选、来源证据和历史建议。你可以直接修改参数值。")
        self.stage_hint.setWordWrap(True)
        review_layout.addWidget(self.stage_hint)

        self.parameter_table = QTableWidget(0, 5)
        self.parameter_table.setHorizontalHeaderLabels(("参数", "参数值", "单位", "来源", "证据/说明"))
        self.parameter_table.horizontalHeader().setStretchLastSection(True)
        self.parameter_table.setColumnWidth(0, 245)
        self.parameter_table.setColumnWidth(1, 155)
        self.parameter_table.setColumnWidth(2, 80)
        self.parameter_table.setColumnWidth(3, 125)
        self.parameter_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.parameter_table.itemChanged.connect(self.on_table_item_changed)
        review_layout.addWidget(self.parameter_table, 1)

        issue_header = QLabel("审核结果")
        issue_header.setObjectName("subTitle")
        review_layout.addWidget(issue_header)
        self.issue_text = QPlainTextEdit()
        self.issue_text.setReadOnly(True)
        self.issue_text.setMaximumHeight(100)
        self.issue_text.setPlaceholderText("点击“审核本阶段”后显示结果。")
        review_layout.addWidget(self.issue_text)
        self.recommendation_widget = QWidget()
        self.recommendation_layout = QHBoxLayout(self.recommendation_widget)
        self.recommendation_layout.setContentsMargins(0, 0, 0, 0)
        self.recommendation_layout.addStretch()
        review_layout.addWidget(self.recommendation_widget)

        actions = QHBoxLayout()
        self.review_button = QPushButton("审核本阶段")
        self.review_button.setObjectName("primaryButton")
        self.review_button.clicked.connect(self.run_review)
        self.review_button.setEnabled(False)
        actions.addWidget(self.review_button)
        self.confirm_button = QPushButton("确认并进入下一步")
        self.confirm_button.clicked.connect(self.confirm_and_next)
        self.confirm_button.setEnabled(False)
        actions.addWidget(self.confirm_button)
        actions.addStretch()
        review_layout.addLayout(actions)
        splitter.addWidget(review_panel)
        splitter.setSizes((510, 920))

    def _apply_style(self):
        self.setStyleSheet("""
        QMainWindow, QWidget { background:#f5f7fa; color:#1e293b; font-family:'Microsoft YaHei'; font-size:13px; }
        #mainTitle { font-size:24px; font-weight:700; color:#173b6c; }
        #sectionTitle { font-size:18px; font-weight:700; color:#173b6c; }
        #subTitle { font-size:14px; font-weight:700; color:#334155; }
        #panel, #sourceBar { background:white; border:1px solid #d9e1ec; border-radius:10px; }
        QPushButton { background:#fff; border:1px solid #b8c6d9; border-radius:5px; padding:7px 13px; }
        QPushButton:hover { border-color:#2d64a8; background:#f2f7fd; }
        QPushButton:disabled { color:#94a3b8; background:#edf1f5; }
        #primaryButton { background:#2368a8; color:white; border-color:#2368a8; font-weight:600; }
        #safeBadge { background:#e8f7ef; color:#276749; border:1px solid #9bd3b4; border-radius:10px; padding:5px 10px; }
        #statusBadge { background:#fff4d6; color:#805b10; border:1px solid #e1c36d; border-radius:10px; padding:5px 10px; }
        QLabel#progressIdle { background:#eaf0f8; color:#5c6d82; border-radius:8px; padding:7px 6px; }
        QTextBrowser, QPlainTextEdit, QTableWidget, QComboBox, QDoubleSpinBox { background:white; border:1px solid #cfd8e5; border-radius:5px; }
        QHeaderView::section { background:#eaf0f8; color:#29415f; padding:7px; border:none; border-right:1px solid #d7e0eb; }
        QTableWidget::item { padding:5px; }
        """)

    def append_chat(self, role, message):
        label = "你" if role == "user" else "管束 Agent"
        color = "#e8f2ff" if role == "user" else "#eef7f1"
        self.conversation.append(
            f'<div style="margin:7px 2px;padding:10px;border-radius:8px;background:{color};">'
            f'<b>{html.escape(label)}</b><br>{html.escape(str(message)).replace(chr(10), "<br>")}</div>'
        )

    def select_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "选择输入文件", "", "设计资料 (*.zip *.pdf *.xlsx *.xlsm *.doc *.docx);;所有文件 (*)")
        if files:
            self.load_inputs(files)

    def use_example_package(self):
        if not EXAMPLE_ZIP.is_file():
            QMessageBox.warning(self, "未找到示例", f"示例压缩包不在预期位置：\n{EXAMPLE_ZIP}")
            return
        self.load_inputs([str(EXAMPLE_ZIP)])

    def load_inputs(self, paths):
        self.selected_paths = [str(Path(path)) for path in paths]
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.bundle = scan_inputs(self.selected_paths)
        finally:
            QApplication.restoreOverrideCursor()
        equipment = identify_equipment(self.bundle)
        self.equipment_combo.clear()
        self.equipment_combo.addItems(equipment)
        self.file_label.setText(f"已选择 {len(paths)} 个输入项，解析 {len(self.bundle.documents)} 个文件，识别 {len(equipment)} 台设备")
        self.append_chat("assistant", f"文件扫描完成：识别到 {len(equipment)} 个设备位号。请确认当前设备、产品型式和 DN，再点击“开始处理”。")
        self._set_progress(1)

    def start_analysis(self):
        equipment = self.equipment_combo.currentText().strip()
        if not equipment:
            QMessageBox.information(self, "请确认设备", "没有识别到设备位号，请在“设备位号”框中手工输入后继续。")
            return
        self.start_with_bundle(self.bundle, equipment, self.product_combo.currentText(), self.dn.value())

    def start_with_bundle(self, bundle, equipment, product_type, dn):
        client = DeepSeekClient(self.config) if self.config.configured else None
        try:
            self.prepared = TubeBundleAgent(self.repository, client).prepare_design(bundle, equipment, product_type, dn)
        except Exception as exc:
            QMessageBox.warning(self, "处理失败", str(exc))
            self.append_chat("assistant", f"处理失败：{exc}")
            return
        self.session = ReviewSession(self.prepared, self.repository)
        for row in self.prepared.trace:
            self.append_chat("assistant", row["message"])
        if self.prepared.conflicts:
            self.append_chat("assistant", f"有 {len(self.prepared.conflicts)} 条问题或冲突，已保留给你人工判断，不会自动覆盖参数。")
        self.review_button.setEnabled(True)
        self.render_stage()

    def render_stage(self):
        if self.session is None:
            return
        signals_were_blocked = self.parameter_table.blockSignals(True)
        self._updating_table = True
        try:
            self.stage_title.setText(f"第 {self.session.current_stage_index + 1}/4 阶段 · {self.session.current_stage}")
            self.review_status.setText(self.session.status)
            rows = self.session.current_parameters
            self.parameter_table.setRowCount(len(rows))
            for row_index, (name, data) in enumerate(rows.items()):
                values = (name, data.get("value", ""), data.get("unit", ""), data.get("source", ""), data.get("evidence", ""))
                for column, value in enumerate(values):
                    item = QTableWidgetItem(str(value))
                    if column != 1 or data.get("derived"):
                        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                    if data.get("derived") and column == 1:
                        item.setBackground(QColor("#eef3f8"))
                    self.parameter_table.setItem(row_index, column, item)
            self._clear_issues()
        finally:
            self._updating_table = False
            self.parameter_table.blockSignals(signals_were_blocked)
        self.confirm_button.setEnabled(self.session.status == "审核通过待确认")
        self._set_progress(2 + self.session.current_stage_index)

    def on_table_item_changed(self, item):
        if self._updating_table or self.session is None or item.column() != 1:
            return
        field = self.parameter_table.item(item.row(), 0).text()
        value = item.text().strip()
        try:
            numeric = float(value)
            value = int(numeric) if numeric.is_integer() else numeric
        except ValueError:
            pass
        current_value = self.session.current_parameters.get(field, {}).get("value")
        try:
            unchanged = float(current_value) == float(value)
        except (TypeError, ValueError):
            unchanged = str(current_value) == str(value)
        if unchanged:
            return
        try:
            self.session.apply_edit(field, value)
        except (KeyError, ValueError) as exc:
            QMessageBox.warning(self, "不能修改", str(exc))
            self.render_stage()
            return
        self.review_status.setText("待审核")
        self.review_status.setStyleSheet("background:#fff4d6;color:#805b10;padding:5px 10px;border-radius:10px;")
        self.issue_text.setPlainText("参数已修改。请点击“审核本阶段”。")
        self.confirm_button.setEnabled(False)
        self._clear_recommendation_buttons()

    def run_review(self):
        if self.session is None:
            return
        result = self.session.run_review()
        self.render_stage()
        if result.passed:
            self.issue_text.setPlainText("全部规则审核通过。请检查内容；确认无误后点击“确认并进入下一步”。")
            self.review_status.setText("审核通过，等待你确认")
            self.review_status.setStyleSheet("background:#e8f7ef;color:#276749;padding:5px 10px;border-radius:10px;")
            self.confirm_button.setEnabled(True)
            self.append_chat("assistant", f"{self.session.current_stage}规则审核通过，但尚未保存。等待你确认后才进入下一步。")
        else:
            self._show_issues(result.issues)
            self.review_status.setText(f"审核不通过 · {len(result.issues)} 项")
            self.review_status.setStyleSheet("background:#ffe8e8;color:#9b2c2c;padding:5px 10px;border-radius:10px;")
            self.confirm_button.setEnabled(False)
            self.append_chat("assistant", f"{self.session.current_stage}有 {len(result.issues)} 项未通过。红色参数旁已给出原因和推荐值。")

    def _show_issues(self, issues):
        lines = []
        self.recommendation_buttons = []
        for issue in issues:
            lines.append(f"• {issue.field}：{issue.message}" + (f"；推荐值 {issue.recommended}" if issue.recommended is not None else ""))
            row = self._find_row(issue.field)
            if row is not None:
                item = self.parameter_table.item(row, 1)
                item.setBackground(QColor("#ffe0e0"))
                item.setForeground(QColor("#9b1c1c"))
                item.setToolTip(issue.message)
            if issue.recommended is not None:
                button = QPushButton(f"{issue.field}：采用 {issue.recommended}")
                button.clicked.connect(lambda _checked=False, issue_id=issue.issue_id: self.apply_recommendation(issue_id))
                self.recommendation_layout.insertWidget(self.recommendation_layout.count() - 1, button)
                self.recommendation_buttons.append(button)
        self.issue_text.setPlainText("\n".join(lines))

    def apply_recommendation(self, issue_id):
        try:
            self.session.apply_recommendation(issue_id)
        except ValueError as exc:
            QMessageBox.warning(self, "无法采用", str(exc))
            return
        self.render_stage()
        self.review_status.setText("已填入推荐值，请再次审核")
        self.issue_text.setPlainText("推荐值已填入。为防止错误数据直接通过，请再次点击“审核本阶段”。")
        self.confirm_button.setEnabled(False)

    def confirm_and_next(self):
        if self.session is None:
            return
        stage = self.session.current_stage
        try:
            result = self.session.confirm_and_advance()
        except (ValueError, RuntimeError) as exc:
            QMessageBox.warning(self, "尚不能进入下一步", str(exc))
            return
        self.append_chat("assistant", f"你已确认“{stage}”，审核快照已写入独立演示数据库。")
        if result == "已完成":
            self.stage_title.setText("四个阶段全部完成")
            self.review_status.setText("已完成并保存")
            self.parameter_table.setRowCount(0)
            self.issue_text.setPlainText(f"设计 #{self.session.design_id} 已完成。所有阶段均经过规则审核和人工确认。")
            self.review_button.setEnabled(False)
            self.confirm_button.setEnabled(False)
            self._set_progress(6)
        else:
            self.render_stage()

    def _find_row(self, field):
        for row in range(self.parameter_table.rowCount()):
            if self.parameter_table.item(row, 0).text() == field:
                return row
        return None

    def _clear_recommendation_buttons(self):
        for button in self.recommendation_buttons:
            self.recommendation_layout.removeWidget(button)
            button.deleteLater()
        self.recommendation_buttons = []

    def _clear_issues(self):
        previous = self._updating_table
        self._updating_table = True
        try:
            self._clear_recommendation_buttons()
            self.issue_text.clear()
            for row in range(self.parameter_table.rowCount()):
                item = self.parameter_table.item(row, 1)
                if item:
                    item.setForeground(QColor("#1e293b"))
                    if not self.session.current_parameters[self.parameter_table.item(row, 0).text()].get("derived"):
                        item.setBackground(QColor("#ffffff"))
        finally:
            self._updating_table = previous

    def _set_progress(self, active):
        for index, label in enumerate(self.progress_labels):
            if index < active:
                label.setStyleSheet("background:#e8f7ef;color:#276749;border-radius:8px;padding:7px 6px;")
            elif index == active:
                label.setStyleSheet("background:#2368a8;color:white;border-radius:8px;padding:7px 6px;font-weight:600;")
            else:
                label.setStyleSheet("background:#eaf0f8;color:#5c6d82;border-radius:8px;padding:7px 6px;")

    def open_settings(self):
        self.config = settings_dialog(self, self.config)
        self.append_chat("assistant", "DeepSeek 设置已更新。只有点击“开始处理”时才会调用模型。" if self.config.configured else "当前保持离线审核模式。")

    def send_note(self):
        text = self.prompt.toPlainText().strip()
        if not text:
            return
        self.append_chat("user", text)
        self.append_chat("assistant", "备注已记录在本次界面中。若备注会改变参数，请直接在右侧表格修改并重新审核。")
        self.prompt.clear()

    def closeEvent(self, event):
        if self._owns_repository:
            self.repository.close()
        super().closeEvent(event)
