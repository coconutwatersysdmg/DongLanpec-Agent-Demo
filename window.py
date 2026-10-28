from __future__ import annotations

import html
import json
import re
import sqlite3
from types import SimpleNamespace

from PyQt5.QtCore import QThread, Qt, pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QAbstractItemView, QDialog, QFrame,
    QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPlainTextEdit, QPushButton,
    QListWidget, QTableWidget, QTableWidgetItem, QTextBrowser,
    QVBoxLayout, QWidget,
)

from ai_support.api_client import DeepSeekClient
from demo_db import DemoRepository
from document_reader import DocumentBundle
from models import STAGES
from pipeline import TubeBundleAgent
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
        self.setWindowTitle("管束 AI 审核助手 Demo")
        self.resize(1760, 1040)
        self.setMinimumSize(1280, 760)
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
        self.sidebar.setFixedWidth(300)
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(22, 22, 22, 22)
        sidebar_layout.setSpacing(8)
        brand = QLabel("管束 AI")
        brand.setObjectName("sidebarTitle")
        sidebar_layout.addWidget(brand)
        self.start_design_button = QPushButton("开始管束设计")
        self.start_design_button.setObjectName("primarySideButton")
        self.start_design_button.clicked.connect(self.start_demo_design)
        sidebar_layout.addWidget(self.start_design_button)
        self.stop_button = QPushButton("停止")
        self.stop_button.setObjectName("sideAction")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_background_task)
        self.stop_button.hide()
        sidebar_layout.addWidget(self.stop_button)
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
        progress_label = QLabel("设计进度")
        progress_label.setObjectName("sidebarSection")
        sidebar_layout.addWidget(progress_label)
        self.stage_buttons = []
        for index, text in enumerate(STAGES):
            button = QPushButton(f"{index + 1}  {text}")
            button.setObjectName("stageButton")
            button.clicked.connect(lambda _checked=False, stage_index=index: self.open_stage(stage_index))
            button.setEnabled(False)
            self.stage_buttons.append(button)
            sidebar_layout.addWidget(button)
        self.progress_labels = self.stage_buttons
        sidebar_layout.addStretch()
        root_layout.addWidget(self.sidebar)

        self.main_panel = QFrame()
        self.main_panel.setObjectName("mainPanel")
        main_layout = QVBoxLayout(self.main_panel)
        main_layout.setContentsMargins(32, 22, 32, 22)
        main_layout.setSpacing(12)
        header = QHBoxLayout()
        title = QLabel("管束设计")
        title.setObjectName("mainTitle")
        header.addWidget(title)
        header.addStretch()
        main_layout.addLayout(header)
        self.conversation = QTextBrowser()
        self.conversation.setObjectName("conversation")
        self.conversation.setOpenExternalLinks(False)
        main_layout.addWidget(self.conversation, 2)

        self.review_panel = QFrame()
        self.review_panel.setObjectName("reviewCard")
        review_layout = QVBoxLayout(self.review_panel)
        review_layout.setContentsMargins(18, 14, 18, 14)
        review_layout.setSpacing(8)
        top = QHBoxLayout()
        self.stage_title = QLabel("尚未开始审核")
        self.stage_title.setObjectName("sectionTitle")
        top.addWidget(self.stage_title)
        top.addStretch()
        self.review_status = QLabel("等待文件")
        self.review_status.setObjectName("statusBadge")
        top.addWidget(self.review_status)
        collapse_review = QPushButton("收起预览")
        collapse_review.clicked.connect(lambda: self.set_review_drawer_visible(False))
        top.addWidget(collapse_review)
        review_layout.addLayout(top)
        self.stage_hint = QLabel("检查并修改参数。")
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
        main_layout.addWidget(self.review_panel, 3)
        self.review_panel.hide()

        composer = QFrame()
        composer.setObjectName("composer")
        composer_layout = QVBoxLayout(composer)
        composer_layout.setContentsMargins(14, 12, 14, 10)
        composer_layout.setSpacing(6)
        self.prompt = QPlainTextEdit()
        self.prompt.setPlaceholderText("输入要求……")
        self.prompt.setMaximumHeight(100)
        composer_layout.addWidget(self.prompt)
        send_row = QHBoxLayout()
        send_row.addStretch()
        send = QPushButton("发送")
        send.setObjectName("sendButton")
        send.clicked.connect(self.send_note)
        send_row.addWidget(send)
        composer_layout.addLayout(send_row)
        main_layout.addWidget(composer)
        root_layout.addWidget(self.main_panel, 1)

    def _apply_style(self):
        self.setStyleSheet("""
        QMainWindow, QWidget { background:#f7f7f5; color:#202124; font-family:'Microsoft YaHei'; font-size:14px; }
        #sidebar { background:#f2f2ee; border-right:1px solid #deded8; }
        #sidebarTitle { font-size:25px; font-weight:700; padding:8px 4px 18px 4px; }
        #sidebarSection { color:#777772; font-weight:600; padding:22px 6px 6px 6px; }
        #mainPanel { background:#ffffff; }
        #mainTitle { font-size:22px; font-weight:700; padding:5px 0 12px 0; }
        #sectionTitle { font-size:18px; font-weight:700; }
        #subTitle { font-size:14px; font-weight:700; color:#444; }
        #conversation { background:#ffffff; border:none; padding:6px; }
        #reviewCard { background:#ffffff; border:1px solid #deded8; border-radius:14px; }
        #composer { background:#ffffff; border:1px solid #d8d8d2; border-radius:16px; }
        QPushButton { background:#fff; border:1px solid #d0d0ca; border-radius:8px; padding:8px 14px; }
        QPushButton:hover { background:#f3f3ef; }
        QPushButton:disabled { color:#aaa; background:#f3f3f0; }
        #sideAction { text-align:left; border:none; background:transparent; padding:10px 12px; }
        #sideAction:hover { background:#e7e7e2; }
        #primarySideButton { text-align:left; background:#e7e7e2; border:none; font-weight:600; padding:11px 12px; }
        #primaryButton, #sendButton { background:#2368a8; color:white; border-color:#2368a8; font-weight:600; }
        #statusBadge { background:#fff4d6; color:#805b10; border:1px solid #e1c36d; border-radius:10px; padding:5px 10px; }
        QLabel#progressIdle { color:#696964; border-radius:8px; padding:8px 12px; }
        QPlainTextEdit, QTableWidget { background:white; border:1px solid #d8d8d2; border-radius:6px; }
        QHeaderView::section { background:#f1f1ed; color:#333; padding:8px; border:none; border-right:1px solid #deded8; }
        QTableWidget::item { padding:5px; }
        """)

    def append_chat(self, role, message):
        label = "你" if role == "user" else "管束 Agent"
        color = "#e8f2ff" if role == "user" else "#eef7f1"
        self.conversation.append(
            f'<div style="margin:7px 2px;padding:10px;border-radius:8px;background:{color};">'
            f'<b>{html.escape(label)}</b><br>{html.escape(str(message)).replace(chr(10), "<br>")}</div>'
        )

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
        self.append_chat("assistant", "预览已生成，请审核。")
        if self.prepared.conflicts:
            self.append_chat("assistant", f"有 {len(self.prepared.conflicts)} 条问题或冲突，已保留给你人工判断，不会自动覆盖参数。")
        self.save_button.setEnabled(True)
        self.render_stage()
        self.set_review_drawer_visible(True)

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
        self.append_chat("assistant", f"你已确认“{stage}”，审核快照已写入独立演示数据库。")
        if result == "已完成":
            self.render_stage()
            self.review_status.setText("已完成并保存")
            self.save_button.setEnabled(False)
            self._set_progress(len(self.progress_labels))
            self.set_review_drawer_visible(True)
        else:
            self.render_stage()

    def go_previous_stage(self):
        if self.session is None or self.session.current_stage_index == 0:
            return
        self.session.go_to_stage(self.session.current_stage_index - 1)
        self.render_stage()
        self.append_chat("assistant", "已返回上一阶段。若修改已确认参数，后续审核会自动失效。")

    def open_history(self):
        designs = self.repository.list_designs()
        dialog = QDialog(self)
        dialog.setWindowTitle("历史审核方案（只读）")
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
            details.setPlainText("还没有历史审核方案。")
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
        finally:
            self._updating_table = previous

    def _set_progress(self, active):
        if self.session is None:
            frontier = 0
        else:
            frontier = next((index for index, approved in enumerate(self.session.approved) if not approved), len(STAGES))
        for index, label in enumerate(self.progress_labels):
            label.setEnabled(self.session is not None and index <= frontier)
            if index < active:
                label.setStyleSheet("background:#e8f7ef;color:#276749;border-radius:8px;padding:7px 6px;")
            elif index == active:
                label.setStyleSheet("background:#2368a8;color:white;border-radius:8px;padding:7px 6px;font-weight:600;")
            else:
                label.setStyleSheet("background:#eaf0f8;color:#5c6d82;border-radius:8px;padding:7px 6px;")

    def open_settings(self):
        self.config = settings_dialog(self, self.config)
        self.append_chat("assistant", "AI 设置已更新。" if self.config.configured else "当前为离线模式。")

    def apply_chat_request(self, text: str) -> bool:
        if self.session is None:
            return False
        for field, data in sorted(self.session.current_parameters.items(), key=lambda item: len(item[0]), reverse=True):
            if field not in text:
                continue
            number = re.search(r"-?\d+(?:\.\d+)?", text.split(field, 1)[1])
            if number is None:
                continue
            if data.get("derived"):
                self.append_chat("assistant", f"{field} 由程序计算，不能直接修改。")
                return False
            value = float(number.group())
            value = int(value) if value.is_integer() else value
            try:
                self.session.apply_edit(field, value)
            except (KeyError, ValueError):
                self.append_chat("assistant", f"{field} 不能直接修改。")
                return False
            self.render_stage()
            self.set_review_drawer_visible(True)
            self.append_chat("assistant", f"已将 {field} 改为 {value}，确认无误后点击保留。")
            return True
        return False

    def send_note(self):
        text = self.prompt.toPlainText().strip()
        if not text:
            return
        self.append_chat("user", text)
        if not self.apply_chat_request(text):
            self.append_chat("assistant", "已记录。")
        self.prompt.clear()

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
