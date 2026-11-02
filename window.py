from __future__ import annotations

import json
import re
import sqlite3
from copy import deepcopy
from types import SimpleNamespace

from PyQt5.QtCore import QThread, QTimer, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont
from PyQt5.QtWidgets import (
    QAbstractItemView, QDialog, QFrame,
    QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPlainTextEdit, QPushButton,
    QListWidget, QScrollArea, QSizePolicy, QTableWidget, QTableWidgetItem, QTextBrowser,
    QVBoxLayout, QWidget,
)

from ai_support.api_client import DeepSeekClient, FIELD_ALIASES
from demo_db import DemoRepository
from document_reader import DocumentBundle
from models import STAGES
from pipeline import TubeBundleAgent
from parameter_editors import ParamValueDelegate, build_combo, editor_spec, style_combo
from review_session import ReviewSession
from settings import load_settings, settings_dialog

class TaskThread(QThread):
    result_ready = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self.fn = fn

    def run(self):
        try:
            result = self.fn()
            if not self.isInterruptionRequested():
                self.result_ready.emit(result)
        except Exception as exc:
            if not self.isInterruptionRequested():
                self.failed.emit(str(exc))


class MessageInput(QPlainTextEdit):
    send_requested = pyqtSignal()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and not (event.modifiers() & Qt.ShiftModifier):
            event.accept()
            self.send_requested.emit()
            return
        super().keyPressEvent(event)


class ChatTranscript(QScrollArea):
    """Widget-backed transcript so message alignment is not dependent on rich-text CSS support."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.message_rows = []
        self._messages = []
        self._content = QWidget()
        self._content.setObjectName("chatContent")
        self._layout = QVBoxLayout(self._content)
        self._layout.setContentsMargins(8, 10, 8, 10)
        self._layout.setSpacing(16)
        self._layout.addStretch()
        self.setWidget(self._content)

    def append_message(self, role: str, text: str) -> None:
        role = "user" if role == "user" else "assistant"
        row = QWidget()
        row.setObjectName("chatRow")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 2, 0, 2)
        row_layout.setSpacing(0)

        message = QFrame()
        message.setProperty("chatRole", role)
        message.setObjectName("userBubble" if role == "user" else "assistantMessage")
        message.setMaximumWidth(780)
        if role == "assistant":
            message.setMinimumWidth(680)
        message.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
        message_layout = QHBoxLayout(message)
        message_layout.setContentsMargins(13 if role == "user" else 0, 9 if role == "user" else 2,
                                          13 if role == "user" else 0, 9 if role == "user" else 2)
        message_layout.setSpacing(11)

        if role == "assistant":
            avatar = QLabel("AI")
            avatar.setObjectName("assistantAvatar")
            avatar.setAlignment(Qt.AlignCenter)
            avatar.setFixedSize(28, 28)
            message_layout.addWidget(avatar, 0, Qt.AlignTop)

        body = QWidget()
        body.setObjectName("chatBody")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(3)
        name = QLabel("你" if role == "user" else "管束助手")
        name.setObjectName("userName" if role == "user" else "assistantName")
        content = QLabel(str(text))
        content.setObjectName("chatMessageText")
        content.setWordWrap(True)
        content.setTextInteractionFlags(Qt.TextSelectableByMouse)
        content.setMaximumWidth(700)
        body_layout.addWidget(name)
        body_layout.addWidget(content)
        message_layout.addWidget(body)

        if role == "user":
            row_layout.addStretch()
            row_layout.addWidget(message, 0, Qt.AlignRight | Qt.AlignTop)
        else:
            row_layout.addWidget(message, 0, Qt.AlignLeft | Qt.AlignTop)
            row_layout.addStretch()

        self._layout.insertWidget(self._layout.count() - 1, row)
        self.message_rows.append(row)
        self._messages.append((role, str(text)))
        QTimer.singleShot(0, self._scroll_to_bottom)

    def _scroll_to_bottom(self) -> None:
        bar = self.verticalScrollBar()
        bar.setValue(bar.maximum())

    def clear(self) -> None:
        for row in self.message_rows:
            self._layout.removeWidget(row)
            row.deleteLater()
        self.message_rows.clear()
        self._messages.clear()

    def toPlainText(self) -> str:
        labels = {"user": "你", "assistant": "管束助手"}
        return "\n".join(f"{labels[role]}\n{text}" for role, text in self._messages)


class DesignWindow(QMainWindow):
    def __init__(self, repository=None):
        super().__init__()
        self.repository = repository or DemoRepository()
        self._owns_repository = repository is None
        self.config = load_settings()
        self.session = None
        self.prepared = None
        self._updating_table = False
        self.recommendation_buttons = []
        self.worker = None
        self._worker_callback = None
        self._worker_cancelled = False
        self.chat_history = []
        self.setWindowTitle("管束 AI 设计助手 Demo")
        self.setFont(QFont("Microsoft YaHei UI", 10))
        self.resize(1440, 900)
        self.setMinimumSize(1100, 700)
        self._build_ui()
        self._apply_style()
        self.append_chat("assistant", "点击左侧“开始管束设计”。")

    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.sidebar = QFrame()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(310)
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(18, 22, 18, 20)
        sidebar_layout.setSpacing(5)
        brand = QLabel("管束 AI")
        brand.setObjectName("sidebarTitle")
        sidebar_layout.addWidget(brand)
        self.start_design_button = QPushButton("开始管束设计")
        self.start_design_button.setObjectName("primarySideButton")
        self.start_design_button.clicked.connect(self.start_demo_design)
        sidebar_layout.addWidget(self.start_design_button)
        self.new_chat_button = QPushButton("新建对话")
        self.new_chat_button.setObjectName("sideAction")
        self.new_chat_button.clicked.connect(self.clear_chat)
        sidebar_layout.addWidget(self.new_chat_button)
        self.stop_button = QPushButton("停止")
        self.stop_button.setObjectName("sideAction")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_background_task)
        self.stop_button.hide()
        sidebar_layout.addWidget(self.stop_button)
        settings_label = QLabel("历史对话")
        settings_label.setObjectName("sidebarSection")
        sidebar_layout.addWidget(settings_label)
        self.conversation_list = QListWidget()
        self.conversation_list.setObjectName("conversationList")
        self.conversation_list.setMaximumHeight(92)
        self.conversation_list.addItem("当前管束设计")
        sidebar_layout.addWidget(self.conversation_list)
        progress_label = QLabel("设计阶段")
        progress_label.setObjectName("sidebarSection")
        sidebar_layout.addWidget(progress_label)
        self.stage_buttons = []
        for index, text in enumerate(STAGES):
            button = QPushButton(f"    {text}")
            button.setObjectName("stageButton")
            button.clicked.connect(lambda _checked=False, stage_index=index: self.open_stage(stage_index))
            button.setEnabled(False)
            self.stage_buttons.append(button)
            sidebar_layout.addWidget(button)
        self.progress_labels = self.stage_buttons
        settings_label = QLabel("通用设置")
        settings_label.setObjectName("sidebarSection")
        sidebar_layout.addWidget(settings_label)
        settings_button = QPushButton("AI 设置")
        settings_button.setObjectName("sideAction")
        settings_button.clicked.connect(self.open_settings)
        sidebar_layout.addWidget(settings_button)
        history_button = QPushButton("历史方案")
        history_button.setObjectName("sideAction")
        history_button.clicked.connect(self.open_history)
        sidebar_layout.addWidget(history_button)
        self.review_toggle_button = QPushButton("查看预览")
        self.review_toggle_button.setObjectName("sideAction")
        self.review_toggle_button.setEnabled(False)
        self.review_toggle_button.clicked.connect(self.toggle_review_drawer)
        sidebar_layout.addWidget(self.review_toggle_button)
        sidebar_layout.addStretch()
        root_layout.addWidget(self.sidebar)

        self.main_panel = QFrame()
        self.main_panel.setObjectName("mainPanel")
        main_layout = QVBoxLayout(self.main_panel)
        main_layout.setContentsMargins(38, 26, 38, 26)
        main_layout.setSpacing(16)
        header = QHBoxLayout()
        self.chat_title = QLabel("管束设计对话")
        self.chat_title.setObjectName("mainTitle")
        header.addWidget(self.chat_title)
        header.addStretch()
        self.clear_chat_button = QPushButton("清空对话")
        self.clear_chat_button.setObjectName("headerAction")
        self.clear_chat_button.clicked.connect(self.clear_chat)
        header.addWidget(self.clear_chat_button)
        main_layout.addLayout(header)
        self.conversation = ChatTranscript()
        self.conversation.setObjectName("conversation")
        main_layout.addWidget(self.conversation, 1)

        self.review_panel = QFrame()
        self.review_panel.setObjectName("reviewCard")
        review_layout = QVBoxLayout(self.review_panel)
        review_layout.setContentsMargins(18, 14, 18, 14)
        review_layout.setSpacing(8)
        top = QHBoxLayout()
        self.stage_title = QLabel("尚未开始")
        self.stage_title.setObjectName("sectionTitle")
        top.addWidget(self.stage_title)
        top.addStretch()
        self.review_status = QLabel("等待文件")
        self.review_status.setObjectName("statusBadge")
        self.review_status.hide()
        top.addWidget(self.review_status)
        collapse_review = QPushButton("收起")
        collapse_review.clicked.connect(lambda: self.set_review_drawer_visible(False))
        top.addWidget(collapse_review)
        review_layout.addLayout(top)
        self.stage_hint = QLabel("检查并修改参数。")
        self.stage_hint.setWordWrap(True)
        self.stage_hint.hide()
        review_layout.addWidget(self.stage_hint)

        self.parameter_table = QTableWidget(0, 5)
        self.parameter_table.setFont(QFont("Microsoft YaHei UI", 11))
        self.parameter_table.setHorizontalHeaderLabels(("参数", "参数值", "单位", "来源", "证据/说明"))
        self.parameter_table.horizontalHeader().setStretchLastSection(True)
        self.parameter_table.horizontalHeader().setMinimumHeight(42)
        self.parameter_table.verticalHeader().setDefaultSectionSize(42)
        self.parameter_table.setAlternatingRowColors(True)
        self.parameter_table.setShowGrid(True)
        self.parameter_table.setColumnWidth(0, 280)
        self.parameter_table.setColumnWidth(1, 180)
        self.parameter_table.setColumnWidth(2, 90)
        self.parameter_table.setColumnWidth(3, 150)
        self.parameter_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.parameter_table.setItemDelegateForColumn(1, ParamValueDelegate(self.parameter_table))
        self.parameter_table.itemChanged.connect(self.on_table_item_changed)
        review_layout.addWidget(self.parameter_table, 1)

        self.issue_container = QFrame()
        self.issue_container.setObjectName("issueContainer")
        issue_layout = QVBoxLayout(self.issue_container)
        issue_layout.setContentsMargins(0, 0, 0, 0)
        issue_layout.setSpacing(8)
        issue_header = QLabel("需要修改")
        issue_header.setObjectName("subTitle")
        issue_layout.addWidget(issue_header)
        self.issue_text = QPlainTextEdit()
        self.issue_text.setReadOnly(True)
        self.issue_text.setMaximumHeight(100)
        issue_layout.addWidget(self.issue_text)
        self.recommendation_widget = QWidget()
        self.recommendation_layout = QHBoxLayout(self.recommendation_widget)
        self.recommendation_layout.setContentsMargins(0, 0, 0, 0)
        self.recommendation_layout.addStretch()
        issue_layout.addWidget(self.recommendation_widget)
        review_layout.addWidget(self.issue_container)
        self.issue_container.hide()

        self.review_actions = QHBoxLayout()
        self.review_actions.addStretch()
        self.save_button = QPushButton("保留")
        self.save_button.setObjectName("primaryButton")
        self.save_button.clicked.connect(self.save_current_stage)
        self.save_button.setEnabled(False)
        self.review_actions.addWidget(self.save_button)
        review_layout.addLayout(self.review_actions)
        main_layout.addWidget(self.review_panel, 6)
        self.review_panel.hide()

        composer = QFrame()
        composer.setObjectName("composer")
        composer_layout = QVBoxLayout(composer)
        composer_layout.setContentsMargins(14, 12, 14, 10)
        composer_layout.setSpacing(6)
        self.prompt = MessageInput()
        self.prompt.setPlaceholderText("给管束 Agent 发送消息")
        self.prompt.setFont(QFont("Microsoft YaHei UI", 11))
        self.prompt.setMinimumHeight(64)
        self.prompt.setMaximumHeight(96)
        self.prompt.send_requested.connect(self.send_note)
        composer_layout.addWidget(self.prompt)
        send_row = QHBoxLayout()
        send_row.addStretch()
        shortcut_hint = QLabel("Enter 发送 · Shift+Enter 换行")
        shortcut_hint.setObjectName("shortcutHint")
        send_row.addWidget(shortcut_hint)
        send_row.addStretch()
        self.send_button = QPushButton("发送")
        self.send_button.setObjectName("sendButton")
        self.send_button.clicked.connect(self.send_note)
        send_row.addWidget(self.send_button)
        composer_layout.addLayout(send_row)
        main_layout.addWidget(composer)
        root_layout.addWidget(self.main_panel, 1)

    def _apply_style(self):
        self.setStyleSheet("""
        QMainWindow, QWidget { background:#fbfaf8; color:#202124; font-family:'Microsoft YaHei UI'; font-size:10pt; }
        #sidebar { background:#f7f7f4; border-right:1px solid #e7e5df; }
        #sidebar QLabel { background:transparent; }
        #sidebarTitle { font-size:20pt; font-weight:600; padding:4px 5px 20px 5px; }
        #sidebarSection { color:#7b7d80; font-size:10pt; font-weight:500; padding:20px 8px 5px 8px; }
        #projectLabel { color:#404246; font-size:11pt; padding:8px 10px 7px 8px; }
        #conversationList { background:transparent; border:none; outline:0; padding:0; }
        #conversationList::item { padding:9px 10px; border-radius:8px; }
        #conversationList::item:selected { background:#e8f0ff; color:#245fb8; }
        #mainPanel { background:#ffffff; }
        #mainTitle { font-size:15pt; font-weight:600; padding:5px 0 14px 0; }
        #sectionTitle { font-size:14pt; font-weight:600; padding:2px 0 4px 0; }
        #subTitle { font-size:10pt; font-weight:600; color:#383838; }
        #conversation, #chatContent, #chatRow, #chatBody { background:#ffffff; border:none; }
        #userBubble { background:#f5f9ff; border:1px solid #cfe0fb; border-radius:14px; }
        #assistantMessage { background:transparent; border:none; }
        #assistantAvatar { background:#eef7f1; color:#087f70; border-radius:14px; font-size:8pt; font-weight:700; }
        #userName { color:#245fb8; font-weight:600; font-size:10pt; }
        #assistantName { color:#087f70; font-weight:600; font-size:10pt; }
        #chatMessageText { color:#202124; font-size:11pt; line-height:1.45; }
        #assistantMessage QLabel, #userBubble QLabel { background:transparent; }
        #shortcutHint { color:#92959a; font-size:9pt; }
        #reviewCard { background:#ffffff; border:1px solid #e1dfda; border-radius:16px; }
        #composer { background:#ffffff; border:1px solid #d9d7d2; border-radius:18px; }
        #issueContainer { background:#fff8f7; border:1px solid #f0ceca; border-radius:10px; padding:10px; }
        QPushButton { background:#fff; border:1px solid #d3d1cc; border-radius:8px; padding:8px 14px; font-size:10pt; }
        QPushButton:hover { background:#f1f0ec; }
        QPushButton:disabled { color:#aaa; background:#f3f3f0; }
        #sideAction { text-align:left; border:none; background:transparent; padding:9px 12px; }
        #sideAction:hover { background:#e8e7e2; }
        #primarySideButton { text-align:left; background:transparent; border:none; font-weight:500; padding:10px 12px; }
        #primarySideButton:hover { background:#ecebe7; }
        #stageButton { text-align:left; border:none; background:transparent; padding:9px 12px; }
        #stageButton:hover { background:#e8e7e2; }
        #primaryButton { min-width:112px; min-height:24px; background:#1f6fb2; color:white; border-color:#1f6fb2; font-weight:600; }
        #sendButton { background:#1f6fb2; color:white; border-color:#1f6fb2; font-weight:600; }
        #headerAction { border:none; background:transparent; color:#74777c; }
        #headerAction:hover { color:#202124; background:#f3f3f0; }
        #statusBadge { background:#fff4d6; color:#805b10; border:1px solid #e1c36d; border-radius:10px; padding:5px 10px; }
        QPlainTextEdit, QTableWidget { background:white; border:1px solid #dedcd7; border-radius:8px; }
        QTableWidget { alternate-background-color:#faf9f7; gridline-color:#e3e4e6; selection-background-color:#e7f1fb; selection-color:#202124; }
        QHeaderView::section { background:#f1f1ef; color:#343434; padding:8px; border:none; border-right:1px solid #dfddd8; font-size:10pt; font-weight:600; }
        QTableWidget::item { padding:6px; }
        """)

    def append_chat(self, role, message):
        text = str(message)
        self.chat_history.append({"role": role, "content": text})
        self.conversation.append_message(role, text)

    def set_review_drawer_visible(self, visible: bool) -> None:
        if visible and self.session is not None:
            self.review_panel.show()
            self.review_toggle_button.setText("收起预览")
            self.review_toggle_button.setEnabled(True)
            return
        self.review_panel.hide()
        self.review_toggle_button.setText("查看预览")
        self.review_toggle_button.setEnabled(self.session is not None)

    def toggle_review_drawer(self) -> None:
        self.set_review_drawer_visible(self.review_panel.isHidden())

    def start_with_bundle(self, bundle, equipment, product_type, dn):
        client = DeepSeekClient(self.config) if self.config.configured else None
        try:
            self.prepared = TubeBundleAgent(self.repository, client).prepare_design(bundle, equipment, product_type, dn)
        except Exception as exc:
            QMessageBox.warning(self, "处理失败", str(exc))
            self.append_chat("assistant", f"处理失败：{exc}")
            return
        self._accept_prepared(self.prepared)

    def start_demo_design(self):
        self.append_chat("user", "开始管束设计")
        self.start_with_bundle(DocumentBundle([]), "DEMO-E-1001", "AEU", 700)

    def _accept_prepared(self, prepared):
        self.prepared = prepared
        self.session = ReviewSession(prepared, self.repository)
        self.chat_title.setText(f"{prepared.equipment_id} · 管束设计")
        self.conversation_list.clear()
        self.conversation_list.addItem(prepared.equipment_id)
        self.conversation_list.setCurrentRow(0)
        self.append_chat("assistant", "四个阶段的设计草稿已生成。你可以直接用自然语言补充要求，也可以点击左侧“查看预览”。")
        if self.prepared.conflicts:
            self.append_chat("assistant", f"有 {len(self.prepared.conflicts)} 条问题或冲突，已保留给你人工判断，不会自动覆盖参数。")
        self.save_button.setEnabled(True)
        self.render_stage()
        self.set_review_drawer_visible(False)

    def _start_worker(self, fn, callback):
        if self.worker is not None and self.worker.isRunning():
            QMessageBox.information(self, "正在处理", "请等待当前步骤结束，或点击“停止”。")
            return
        self._worker_cancelled = False
        self._worker_callback = callback
        self.worker = TaskThread(fn, self)
        self.worker.result_ready.connect(self._worker_result)
        self.worker.failed.connect(self._worker_error)
        self.worker.finished.connect(self._worker_finished)
        self.stop_button.setEnabled(True)
        self.worker.start()

    def _worker_result(self, result):
        if not self._worker_cancelled and self._worker_callback:
            self._worker_callback(result)

    def _worker_error(self, message):
        if self._worker_cancelled:
            return
        self.review_status.setText("处理失败，可重试")
        self.append_chat("assistant", f"处理失败：{message}")
        QMessageBox.warning(self, "处理失败", message)

    def _worker_finished(self):
        self.stop_button.setEnabled(False)
        self.send_button.setEnabled(True)
        if self.worker is not None:
            self.worker.deleteLater()
        self.worker = None
        self._worker_callback = None

    def stop_background_task(self):
        if self.worker is None:
            return
        self._worker_cancelled = True
        self.worker.requestInterruption()
        self.stop_button.setEnabled(False)
        self.review_status.setText("已请求停止")
        self.append_chat("assistant", "已请求停止。当前文件页或网络请求结束后会安全停止，不会保存未审核数据。")

    def render_stage(self):
        if self.session is None:
            return
        signals_were_blocked = self.parameter_table.blockSignals(True)
        self._updating_table = True
        try:
            self.stage_title.setText(self.session.current_stage)
            self.review_status.setText(self.session.status)
            rows = self.session.current_parameters
            # setRowCount alone can leave index widgets alive until the next event
            # cycle.  Remove them first so repeated previews never stack controls.
            for old_row in range(self.parameter_table.rowCount()):
                widget = self.parameter_table.cellWidget(old_row, 1)
                if widget is not None:
                    self.parameter_table.removeCellWidget(old_row, 1)
                    widget.deleteLater()
            self.parameter_table.setRowCount(0)
            self.parameter_table.setRowCount(len(rows))
            product_type = self.session.parameters.get("管板型式", {}).get("产品型式", {}).get("value", "")
            for row_index, (name, data) in enumerate(rows.items()):
                values = (name, data.get("value", ""), data.get("unit", ""), data.get("source", ""), data.get("evidence", ""))
                for column, value in enumerate(values):
                    item = QTableWidgetItem(str(value))
                    if column != 1 or data.get("derived") or not data.get("editable", True):
                        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                    if data.get("derived") and column == 1:
                        item.setBackground(QColor("#eef3f8"))
                    self.parameter_table.setItem(row_index, column, item)
                if data.get("editable", True) and not data.get("derived"):
                    spec = editor_spec(name, rows, product_type)
                    if spec is not None:
                        combo = build_combo(
                            spec,
                            data.get("value", ""),
                            lambda text, row=row_index: self._commit_combo_value(row, text),
                            self.parameter_table,
                        )
                        style_combo(combo)
                        self.parameter_table.setCellWidget(row_index, 1, combo)
            self._clear_issues()
        finally:
            self._updating_table = False
            self.parameter_table.blockSignals(signals_were_blocked)
        self.save_button.setEnabled(True)
        self._set_progress(self.session.current_stage_index)

    def open_stage(self, index: int) -> None:
        if self.session is None or not 0 <= index < len(STAGES):
            return
        try:
            self.session.go_to_stage(index)
        except ValueError:
            return
        self.render_stage()
        self.set_review_drawer_visible(True)

    def on_table_item_changed(self, item):
        if self._updating_table or self.session is None or item.column() != 1:
            return
        self._commit_table_value(item.row(), item.text())

    def _commit_combo_value(self, row: int, text: str) -> None:
        """Route source-style combo edits through the same review-session path."""
        if self._updating_table or self.session is None:
            return
        item = self.parameter_table.item(row, 1)
        if item is not None:
            blocked = self.parameter_table.blockSignals(True)
            item.setText(str(text).strip())
            self.parameter_table.blockSignals(blocked)
        field_item = self.parameter_table.item(row, 0)
        field = field_item.text() if field_item is not None else ""
        self._commit_table_value(row, text)
        # The production UI rebuilds the pass-form selector when pass count changes.
        if field == "管程程数":
            self.render_stage()

    def _commit_table_value(self, row: int, raw_value) -> None:
        field_item = self.parameter_table.item(row, 0)
        if field_item is None:
            return
        field = field_item.text()
        value = str(raw_value).strip()
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
        self.review_status.setText("已修改")
        self.issue_container.hide()
        self._clear_recommendation_buttons()

    def save_current_stage(self):
        if self.session is None:
            return
        result = self.session.run_review()
        self.render_stage()
        if not result.passed:
            self._show_issues(result.issues)
            self.review_status.setText(f"需要修改 · {len(result.issues)} 项")
            self.review_status.setStyleSheet("background:#ffe8e8;color:#9b2c2c;padding:5px 10px;border-radius:10px;")
            self.append_chat("assistant", f"{self.session.current_stage}有 {len(result.issues)} 项需要修改。")
            return
        answer = QMessageBox.question(
            self,
            "确认保留",
            f"确认保留“{self.session.current_stage}”的当前参数吗？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if answer != QMessageBox.Yes:
            self.review_status.setText("未保留")
            return
        self.confirm_and_next()

    def _show_issues(self, issues):
        self.issue_container.show()
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
                combo = self.parameter_table.cellWidget(row, 1)
                if combo is not None:
                    style_combo(combo)
                    combo.setStyleSheet(combo.styleSheet() + "QComboBox{border:1px solid #d04b4b;background:#fff4f4;}")
                    combo.setToolTip(issue.message)
            if issue.recommended is not None:
                button = QPushButton(f"{issue.field}：采用 {issue.recommended}")
                button.clicked.connect(lambda _checked=False, issue_id=issue.issue_id: self.apply_recommendation(issue_id))
                self.recommendation_layout.insertWidget(self.recommendation_layout.count() - 1, button)
                self.recommendation_buttons.append(button)
        if any(issue.issue_id.startswith("conflict:") for issue in issues):
            button = QPushButton("我已阅读冲突并人工处理")
            button.clicked.connect(self.acknowledge_conflicts)
            self.recommendation_layout.insertWidget(self.recommendation_layout.count() - 1, button)
            self.recommendation_buttons.append(button)
        self.issue_text.setPlainText("\n".join(lines))

    def acknowledge_conflicts(self):
        if self.session and self.session.acknowledge_conflicts():
            self.render_stage()
            self.review_status.setText("冲突已处理")

    def apply_recommendation(self, issue_id):
        try:
            self.session.apply_recommendation(issue_id)
        except ValueError as exc:
            QMessageBox.warning(self, "无法采用", str(exc))
            return
        self.render_stage()
        self.review_status.setText("已填入推荐值")

    def confirm_and_next(self):
        if self.session is None:
            return
        stage = self.session.current_stage
        try:
            result = self.session.confirm_and_advance()
        except (ValueError, RuntimeError) as exc:
            QMessageBox.warning(self, "尚不能进入下一步", str(exc))
            return
        except sqlite3.Error as exc:
            self.review_status.setText("保存失败，可重试")
            self.issue_container.show()
            self.issue_text.setPlainText(f"保存失败：{exc}\n请检查磁盘或数据库后再次点击保留。")
            self.save_button.setEnabled(True)
            self.append_chat("assistant", f"独立演示数据库保存失败，可重试：{exc}")
            QMessageBox.warning(self, "保存失败", str(exc))
            return
        self.append_chat("assistant", f"已保留“{stage}”。")
        if result == "已完成":
            self.render_stage()
            self.review_status.setText("已完成并保存")
            self.save_button.setEnabled(False)
            self._set_progress(len(self.progress_labels))
            self.set_review_drawer_visible(True)
        else:
            self.render_stage()

    def open_history(self):
        designs = self.repository.list_designs()
        dialog = QDialog(self)
        dialog.setWindowTitle("历史方案（只读）")
        dialog.resize(780, 560)
        layout = QVBoxLayout(dialog)
        listing = QListWidget()
        for design in designs:
            listing.addItem(f"#{design['id']}  {design['equipment_id']}  {design['product_type']}  DN{design['dn']:g}  {design['status']}")
            listing.item(listing.count() - 1).setData(Qt.UserRole, design["id"])
        details = QTextBrowser()
        layout.addWidget(listing)
        layout.addWidget(details, 1)
        buttons = QHBoxLayout()
        copy_button = QPushButton("基于此方案创建新版本")
        close_button = QPushButton("关闭")
        buttons.addWidget(copy_button)
        buttons.addStretch()
        buttons.addWidget(close_button)
        layout.addLayout(buttons)

        def show_snapshot():
            item = listing.currentItem()
            if item:
                snapshot = self.repository.load_design_snapshot(item.data(Qt.UserRole))
                details.setPlainText(json.dumps(snapshot, ensure_ascii=False, indent=2))

        def copy_snapshot():
            item = listing.currentItem()
            if not item:
                return
            source_id = item.data(Qt.UserRole)
            snapshot = self.repository.load_design_snapshot(source_id)
            clone = self.repository.clone_design(source_id)
            base = self.repository.load_base_context(clone["product_type"], clone["dn"])
            conflicts = []
            for stage, payload in snapshot["stages"].items():
                if payload:
                    base[stage] = payload.get("parameters", base[stage])
                    conflicts.extend(payload.get("conflicts", []))
            prepared = SimpleNamespace(
                design_id=clone["id"], version=clone["version"], base_context=base,
                evidence=[], conflicts=conflicts, history=self.repository.lookup_history(clone["product_type"], clone["dn"]), proposals=[], trace=[],
            )
            dialog.accept()
            self._accept_prepared(prepared)
            self.append_chat("assistant", f"已从历史方案 #{source_id} 创建新版本 #{clone['id']}。旧版本保持只读。")

        listing.currentItemChanged.connect(lambda *_: show_snapshot())
        copy_button.clicked.connect(copy_snapshot)
        close_button.clicked.connect(dialog.reject)
        if listing.count():
            listing.setCurrentRow(0)
        else:
            details.setPlainText("还没有历史方案。")
            copy_button.setEnabled(False)
        dialog.exec_()

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
            self.issue_container.hide()
            for row in range(self.parameter_table.rowCount()):
                item = self.parameter_table.item(row, 1)
                if item:
                    item.setForeground(QColor("#1e293b"))
                    if not self.session.current_parameters[self.parameter_table.item(row, 0).text()].get("derived"):
                        item.setBackground(QColor("#ffffff"))
                combo = self.parameter_table.cellWidget(row, 1)
                if combo is not None:
                    style_combo(combo)
                    combo.setToolTip("")
        finally:
            self._updating_table = previous

    def _set_progress(self, active):
        if self.session is None:
            frontier = 0
        else:
            frontier = next((index for index, approved in enumerate(self.session.approved) if not approved), len(STAGES))
        for index, label in enumerate(self.progress_labels):
            label.setEnabled(self.session is not None and index <= frontier)
            if index == active:
                label.setStyleSheet("background:#e9e9e5;color:#202124;border-radius:8px;padding:9px 12px;font-weight:500;text-align:left;")
            elif index < active:
                label.setStyleSheet("background:transparent;color:#5d6f61;border-radius:8px;padding:9px 12px;text-align:left;")
            else:
                label.setStyleSheet("background:transparent;color:#85878b;border-radius:8px;padding:9px 12px;text-align:left;")

    def open_settings(self):
        self.config = settings_dialog(self, self.config)
        self.append_chat("assistant", "AI 设置已更新。" if self.config.configured else "当前为离线模式。")

    def _local_chat_actions(self, text: str) -> list[dict]:
        if self.session is None:
            return []
        aliases_by_field = {}
        for alias, canonical in FIELD_ALIASES.items():
            aliases_by_field.setdefault(canonical, []).append(alias)
        candidates = []
        for stage, rows in self.session.parameters.items():
            for field, data in rows.items():
                if data.get("derived") or not data.get("editable", True):
                    continue
                names = [field] + aliases_by_field.get(field, [])
                candidates.append((max(map(len, names)), stage, field, data, names))
        actions, used_fields = [], set()
        for _length, stage, field, data, names in sorted(candidates, reverse=True):
            if field in used_fields:
                continue
            matched_name = next((name for name in sorted(names, key=len, reverse=True) if name in text), None)
            if not matched_name:
                continue
            suffix = text.split(matched_name, 1)[1]
            number = re.search(r"(?:改成|改为|设为|设置为|调整为|增加到|改)?\s*(-?\d+(?:\.\d+)?)", suffix)
            value = None
            if number is not None:
                numeric = float(number.group(1))
                value = int(numeric) if numeric.is_integer() else numeric
            else:
                spec = editor_spec(
                    field,
                    self.session.parameters[stage],
                    self.session.parameters["管板型式"]["产品型式"]["value"],
                )
                if spec is not None:
                    value = next((option for option in spec.options if option in suffix), None)
            if value is not None:
                actions.append({"stage": stage, "parameter": field, "value": value})
                used_fields.add(field)
        return actions

    def apply_chat_request(self, text: str) -> bool:
        actions = self._local_chat_actions(text)
        if not actions:
            return False
        return self.handle_chat_result({
            "reply": "已按你的要求更新设计草稿。",
            "actions": actions,
            "rejected": [],
        })

    def handle_chat_result(self, result) -> bool:
        if self.session is None:
            self.append_chat("assistant", "请先点击“开始管束设计”。")
            return False
        result = result if isinstance(result, dict) else {}
        execution = self.session.apply_draft_actions(result.get("actions", []))
        rejected = list(result.get("rejected", [])) + list(execution.get("rejected", []))
        lines = [str(result.get("reply", "")).strip() or "我已经检查了这条要求。"]
        applied = execution.get("applied", [])
        if applied:
            lines.append("\n已更新草稿：")
            for item in applied:
                lines.append(
                    f"• {item['stage']}｜{item['parameter']}：{item.get('old_value', '')} → {item.get('value', '')}"
                )
            lines.append("\n这些修改尚未入库，到对应阶段检查并点击“保留”后才会保存。")
        if rejected:
            lines.append("\n未执行：")
            for item in rejected:
                target = "｜".join(filter(None, [str(item.get("stage", "")), str(item.get("parameter", ""))])) or "该要求"
                lines.append(f"• {target}：{item.get('reason', '无法执行')}")
        self.append_chat("assistant", "\n".join(lines))
        if applied:
            self.render_stage()
            self.review_toggle_button.setEnabled(True)
        return bool(applied)

    def send_note(self):
        text = self.prompt.toPlainText().strip()
        if not text:
            return
        self.prompt.clear()
        if self.worker is not None and self.worker.isRunning():
            self.append_chat("assistant", "上一条要求还在处理中，请稍候。")
            return
        self.append_chat("user", text)
        if self.session is None:
            self.append_chat("assistant", "请先点击左侧“开始管束设计”，生成草稿后我才能修改参数。")
            return
        if self.config.configured:
            client = DeepSeekClient(self.config)
            history = deepcopy(self.chat_history[:-1])
            context = deepcopy(self.session.parameters)
            current_stage = self.session.current_stage
            self.send_button.setEnabled(False)
            self._start_worker(
                lambda: client.chat(history, context, current_stage, text),
                self.handle_chat_result,
            )
            return
        if not self.apply_chat_request(text):
            self.append_chat(
                "assistant",
                "离线模式暂时只能识别明确的参数修改，例如“折流板间距改成 500”。如需正常问答和更灵活的表达，请在 AI 设置中填写 DeepSeek API Key。",
            )

    def clear_chat(self):
        if self.worker is not None and self.worker.isRunning():
            self.append_chat("assistant", "当前要求仍在处理中，完成后再新建对话。")
            return
        self.conversation.clear()
        self.chat_history = []
        self.append_chat("assistant", "对话已清空，可以继续描述你的管束设计要求。")

    def closeEvent(self, event):
        if self.worker is not None and self.worker.isRunning():
            self.worker.requestInterruption()
            self._worker_cancelled = True
            self.review_status.setText("正在安全停止，请稍候再关闭")
            event.ignore()
            return
        if self._owns_repository:
            self.repository.close()
        super().closeEvent(event)
