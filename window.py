"""管束设计 Agent 主窗口：聊天式界面 + 四个正式 Tab 的预览卡片。

界面沿用 Demo 原有简洁聊天风格：用户消息靠右、AI 回复靠左、Enter 发送、
Shift+Enter 换行。左侧导航使用正式程序的四个 Tab 名称，点击后在聊天区域
展开该 Tab 的预览（管板型式/布管/管-板连接/轴向设计），预览底部只有一个“保留”。
"""
from __future__ import annotations

import json
import re
from copy import deepcopy

from PyQt5.QtCore import QThread, QTimer, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ai_support.api_client import CANONICAL_FIELDS, FIELD_ALIASES, DeepSeekClient
from bundle.page import TubeLayoutPage
from bundle.stages import AxialStage, SheetFormStage, TubeConnectionStage
from db.production import DatabaseUnavailable, ProductionRepository, SaveFailed
from models import STAGES
from session import DesignSession
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
        except Exception as exc:  # noqa: BLE001 - 交给界面显示
            if not self.isInterruptionRequested():
                self.failed.emit(str(exc))


class MessageInput(QPlainTextEdit):
    send_requested = pyqtSignal()

    MIN_HEIGHT = 46
    MAX_HEIGHT = 132

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.textChanged.connect(self._autosize)
        self.setFixedHeight(self.MIN_HEIGHT)

    def _autosize(self):
        if self.viewport().width() < 120:
            return
        metrics = self.fontMetrics()
        usable = max(120, self.viewport().width() - 6)
        lines = 0
        block = self.document().begin()
        while block.isValid():
            advance = metrics.horizontalAdvance(block.text() or " ")
            lines += max(1, -(-advance // usable))
            block = block.next()
        needed = 14 + lines * (metrics.height() + 3)
        target = max(self.MIN_HEIGHT, min(self.MAX_HEIGHT, needed))
        if target != self.height():
            self.setFixedHeight(target)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._autosize()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and not (event.modifiers() & Qt.ShiftModifier):
            event.accept()
            self.send_requested.emit()
            return
        super().keyPressEvent(event)


class ChatTranscript(QScrollArea):
    """Widget-backed transcript so message alignment is not dependent on rich-text CSS support."""

    MAX_TEXT_WIDTH = 900

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.message_rows = []
        self._messages = []
        self._transient_label: QLabel | None = None
        self._content = QWidget()
        self._content.setObjectName("chatContent")
        self._layout = QVBoxLayout(self._content)
        self._layout.setContentsMargins(0, 6, 0, 6)
        self._layout.setSpacing(18)
        self._layout.addStretch()
        self.setWidget(self._content)

    def append_message(self, role: str, text: str, transient: bool = False) -> QLabel:
        role = "user" if role == "user" else "assistant"
        row = QWidget()
        row.setObjectName("chatRow")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(0)

        message = QFrame()
        message.setProperty("chatRole", role)
        message.setObjectName("userMessage" if role == "user" else "assistantMessage")
        message.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
        body = QVBoxLayout(message)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(5)

        if role == "assistant":
            message.setMaximumWidth(self.MAX_TEXT_WIDTH + 34)
            message.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            head = QHBoxLayout()
            head.setContentsMargins(0, 0, 0, 0)
            head.setSpacing(8)
            avatar = QLabel("AI")
            avatar.setObjectName("assistantAvatar")
            avatar.setAlignment(Qt.AlignCenter)
            avatar.setFixedSize(24, 24)
            name = QLabel("管束助手")
            name.setObjectName("assistantName")
            head.addWidget(avatar, 0, Qt.AlignVCenter)
            head.addWidget(name, 0, Qt.AlignVCenter)
            head.addStretch()
            body.addLayout(head)
            content = QLabel(str(text))
            content.setObjectName("chatMessageText")
            content.setWordWrap(True)
            content.setMaximumWidth(self.MAX_TEXT_WIDTH)
            content.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            content.setTextInteractionFlags(Qt.TextSelectableByMouse)
            body.addWidget(content)
            row_layout.addWidget(message, 1)
            row_layout.addStretch(0)
        else:
            message.setMaximumWidth(560)
            message.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
            name = QLabel("你")
            name.setObjectName("userName")
            name.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            bubble = QFrame()
            bubble.setObjectName("userBubble")
            bubble_layout = QVBoxLayout(bubble)
            bubble_layout.setContentsMargins(14, 9, 14, 10)
            bubble_layout.setSpacing(0)
            content = QLabel(str(text))
            content.setObjectName("chatMessageText")
            content.setWordWrap(True)
            content.setMaximumWidth(510)
            content.setTextInteractionFlags(Qt.TextSelectableByMouse)
            bubble_layout.addWidget(content)
            body.addWidget(name, 0, Qt.AlignRight)
            body.addWidget(bubble)
            row_layout.addStretch()
            row_layout.addWidget(message, 0, Qt.AlignRight | Qt.AlignTop)

        self._layout.insertWidget(self._layout.count() - 1, row)
        self.message_rows.append(row)
        self._messages.append((role, str(text)))
        # 只有“操作反馈”类消息可以就地替换；普通对话/卡片之后再来状态提示就另起一条
        self._transient_label = content if transient and role == "assistant" else None
        QTimer.singleShot(0, self._scroll_to_bottom)
        return content

    def update_transient(self, text: str) -> bool:
        """把最新一条状态提示改成新文本（不新增气泡），成功返回 True。"""
        if self._transient_label is None:
            return False
        self._transient_label.setText(str(text))
        if self._messages:
            role, _ = self._messages[-1]
            self._messages[-1] = (role, str(text))
        return True

    def append_widget(self, widget: QWidget) -> None:
        self._transient_label = None
        self._layout.insertWidget(self._layout.count() - 1, widget)
        self.message_rows.append(widget)
        QTimer.singleShot(0, self._scroll_to_bottom)

    def remove_widget(self, widget: QWidget | None) -> None:
        if widget is None:
            return
        if widget in self.message_rows:
            self.message_rows.remove(widget)
        self._layout.removeWidget(widget)
        widget.setParent(None)
        widget.deleteLater()

    def _scroll_to_bottom(self) -> None:
        bar = self.verticalScrollBar()
        bar.setValue(bar.maximum())

    def scroll_to(self, widget: QWidget) -> None:
        # 直接滚到底：预览卡片高度≈可视高度，滚到底即可完整看到卡片与“保留”
        self._scroll_to_bottom()
        QTimer.singleShot(0, self._scroll_to_bottom)

    def clear(self) -> None:
        for row in self.message_rows:
            self._layout.removeWidget(row)
            row.deleteLater()
        self.message_rows.clear()
        self._messages.clear()

    def toPlainText(self) -> str:
        labels = {"user": "你", "assistant": "管束助手"}
        return "\n".join(f"{labels[role]}\n{text}" for role, text in self._messages)


class PreviewCard(QFrame):
    """聊天区域内的阶段预览卡片。"""

    def __init__(self, stage: str, page: QWidget, approved: bool = False, parent=None):
        super().__init__(parent)
        self.setObjectName("previewCard")
        self.setMinimumHeight(320)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 12, 18, 12)
        layout.setSpacing(8)
        head = QHBoxLayout()
        title = QLabel(stage)
        title.setObjectName("sectionTitle")
        head.addWidget(title)
        head.addSpacing(8)
        self.badge = QLabel("已保留" if approved else "草稿 · 检查后点“保留”")
        self.badge.setObjectName("statusBadge" if not approved else "keptBadge")
        head.addWidget(self.badge)
        head.addStretch()
        layout.addLayout(head)
        self.page = page
        layout.addWidget(page, 1)

    def fit_to(self, available: int) -> None:
        """卡片高度按页面实际需要定高，最多不超过聊天区可视高度。"""
        need = self.page.sizeHint().height() + 56
        self.setFixedHeight(max(min(need, available), 300))


class DesignWindow(QMainWindow):
    def __init__(self, repository=None):
        super().__init__()
        self._owns_repository = repository is None
        self.repository = repository or ProductionRepository()
        self.config = load_settings()
        self.session: DesignSession | None = None
        self.pages: dict[int, QWidget] = {}
        self.card: PreviewCard | None = None
        self.worker = None
        self._worker_callback = None
        self._worker_cancelled = False
        self.chat_history: list[dict] = []
        self.db_status = "未连接"
        # 离屏截图/自动验收用：跳过模态弹窗，并且绝不真正写库
        self.headless = False
        self.setWindowTitle("管束设计 Agent")
        self.setFont(QFont("Microsoft YaHei UI", 10))
        self.resize(1720, 1020)
        self.setMinimumSize(1280, 820)
        self._build_ui()
        self._apply_style()
        self._check_database()
        self.append_chat(
            "assistant",
            "你好，我是管束设计助手。\n"
            "点击左侧“开始管束设计”，我会读取正式数据库里前序模块的数据，按"
            "“管板型式 → 布管 → 管-板连接 → 轴向设计”四个 Tab 生成草稿。\n"
            "布管图形和右侧管孔数量表都可以直接操作；四个 Tab 都保留后才写库。",
        )

    # ------------------------------------------------------------------ 布局
    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.sidebar = QFrame()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(288)
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(16, 20, 16, 14)
        sidebar_layout.setSpacing(2)

        brand = QLabel("管束设计")
        brand.setObjectName("sidebarTitle")
        sidebar_layout.addWidget(brand)
        subtitle = QLabel("Agent Demo")
        subtitle.setObjectName("sidebarSubtitle")
        sidebar_layout.addWidget(subtitle)
        sidebar_layout.addSpacing(16)

        self.start_design_button = QPushButton("开始管束设计")
        self.start_design_button.setObjectName("primarySideButton")
        self.start_design_button.setCursor(Qt.PointingHandCursor)
        self.start_design_button.clicked.connect(self.start_design)
        sidebar_layout.addWidget(self.start_design_button)

        for text, slot in (("新建对话", self.clear_chat), ("选择产品", self.open_product_list)):
            button = QPushButton(text)
            button.setObjectName("sideAction")
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(slot)
            sidebar_layout.addWidget(button)

        stage_label = QLabel("设计 Tab")
        stage_label.setObjectName("sidebarSection")
        sidebar_layout.addWidget(stage_label)
        self.stage_buttons: list[QPushButton] = []
        for index, text in enumerate(STAGES):
            button = QPushButton(text)
            button.setObjectName("stageButton")
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, i=index: self.open_stage(i))
            button.setEnabled(False)
            self.stage_buttons.append(button)
            sidebar_layout.addWidget(button)

        sidebar_layout.addStretch()
        tools = QHBoxLayout()
        tools.setSpacing(2)
        settings_button = QPushButton("AI 设置")
        settings_button.setObjectName("tinyAction")
        settings_button.setCursor(Qt.PointingHandCursor)
        settings_button.clicked.connect(self.open_settings)
        tools.addWidget(settings_button)
        tools.addStretch()
        sidebar_layout.addLayout(tools)
        sidebar_layout.addSpacing(6)
        self.model_label = QLabel("")
        self.model_label.setObjectName("footerLabel")
        sidebar_layout.addWidget(self.model_label)
        self.db_label = QLabel("")
        self.db_label.setObjectName("footerLabel")
        self.db_label.setWordWrap(True)
        sidebar_layout.addWidget(self.db_label)
        self._refresh_model_label()
        root_layout.addWidget(self.sidebar)

        self.main_panel = QFrame()
        self.main_panel.setObjectName("mainPanel")
        main_layout = QVBoxLayout(self.main_panel)
        main_layout.setContentsMargins(40, 18, 40, 14)
        main_layout.setSpacing(0)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        self.chat_title = QLabel("管束设计对话")
        self.chat_title.setObjectName("mainTitle")
        header.addWidget(self.chat_title)
        header.addStretch()
        self.clear_chat_button = QPushButton("清空对话")
        self.clear_chat_button.setObjectName("headerAction")
        self.clear_chat_button.setCursor(Qt.PointingHandCursor)
        self.clear_chat_button.clicked.connect(self.clear_chat)
        header.addWidget(self.clear_chat_button)
        main_layout.addLayout(header)

        self.conversation = ChatTranscript()
        self.conversation.setObjectName("conversation")
        self.conversation.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.conversation.setMinimumHeight(240)
        main_layout.addWidget(self.conversation, 1)

        composer_wrap = QWidget()
        wrap_layout = QVBoxLayout(composer_wrap)
        wrap_layout.setContentsMargins(0, 8, 0, 0)
        wrap_layout.setSpacing(7)
        composer = QFrame()
        composer.setObjectName("composer")
        composer_layout = QHBoxLayout(composer)
        composer_layout.setContentsMargins(16, 8, 10, 8)
        composer_layout.setSpacing(8)
        self.prompt = MessageInput()
        self.prompt.setObjectName("composerInput")
        self.prompt.setPlaceholderText("描述你要做的操作，例如“换热管中心距改成34毫米”“重新布管，尽量多布”…")
        self.prompt.setFont(QFont("Microsoft YaHei UI", 11))
        self.prompt.setFrameShape(QFrame.NoFrame)
        self.prompt.send_requested.connect(self.send_note)
        composer_layout.addWidget(self.prompt, 1)
        self.send_button = QPushButton("发送")
        self.send_button.setObjectName("sendButton")
        self.send_button.setCursor(Qt.PointingHandCursor)
        self.send_button.clicked.connect(self.send_note)
        composer_layout.addWidget(self.send_button, 0, Qt.AlignBottom)
        wrap_layout.addWidget(composer)
        hint = QLabel("Enter 发送 · Shift+Enter 换行 · Ctrl+滚轮缩放布管图 · 拖动空白处框选")
        hint.setObjectName("shortcutHint")
        hint.setAlignment(Qt.AlignCenter)
        wrap_layout.addWidget(hint)
        main_layout.addWidget(composer_wrap)
        root_layout.addWidget(self.main_panel, 1)

    def _refresh_model_label(self):
        if not hasattr(self, "model_label"):
            return
        if self.config.configured:
            self.model_label.setText(f"DeepSeek · {self.config.model}")
        else:
            self.model_label.setText("离线模式 · 未配置 DeepSeek")

    def _check_database(self):
        try:
            ok, message = self.repository.ping()
        except DatabaseUnavailable as exc:
            ok, message = False, str(exc)
        self.db_status = message
        if hasattr(self, "db_label"):
            self.db_label.setText(("正式库：" if ok else "正式库不可用：") + message)
            self.db_label.setStyleSheet("color:#8f949c;font-size:8.5pt;" if ok else "color:#b04a42;font-size:8.5pt;")

    def _apply_style(self):
        self.setStyleSheet("""
        QMainWindow, QWidget { background:#ffffff; color:#1f2329; font-family:'Microsoft YaHei UI'; font-size:10.5pt; }
        #sidebar { background:#fafafa; border-right:1px solid #ececea; }
        #sidebar QLabel { background:transparent; }
        #sidebarTitle { font-size:15pt; font-weight:600; color:#1b1e23; padding:2px 6px 0 6px; }
        #sidebarSubtitle { color:#a2a6ad; font-size:9pt; padding:2px 6px 0 6px; }
        #sidebarSection { color:#a2a6ad; font-size:9pt; padding:16px 8px 6px 8px; }
        #footerLabel { color:#a8acb3; font-size:8.5pt; padding:1px 6px; }
        #mainPanel { background:#ffffff; }
        #mainTitle { font-size:14pt; font-weight:600; color:#1b1e23; padding:2px 0 10px 0; }
        #sectionTitle { font-size:13pt; font-weight:600; padding:2px 0 4px 0; }
        #conversation, #chatContent, #chatRow { background:#ffffff; border:none; }
        #assistantMessage, #userMessage { background:transparent; border:none; }
        #assistantAvatar { background:#eef4ff; color:#3b6fd4; border-radius:9px; font-size:8pt; font-weight:700; }
        #assistantName { color:#4a76cf; font-size:9pt; font-weight:600; }
        #userName { color:#a9b2c0; font-size:9pt; padding:0 6px 0 0; }
        #chatMessageText { color:#22262c; font-size:10.5pt; }
        #userBubble { background:#f4f8ff; border:1px solid #dbe6fb; border-radius:14px; }
        #composer { background:#ffffff; border:1px solid #e2e3e6; border-radius:16px; }
        #composer:hover { border-color:#cfd6e2; }
        #composerInput { background:transparent; border:none; color:#1f2329; font-size:10.5pt; padding:5px 2px; }
        #shortcutHint { color:#a8acb3; font-size:8.5pt; }
        #previewCard { background:#ffffff; border:1px solid #e6e5e2; border-radius:16px; }
        #statusBadge { background:#fff4d6; color:#805b10; border:1px solid #e1c36d; border-radius:10px; padding:3px 9px; font-size:9pt; }
        #keptBadge { background:#eaf7ee; color:#256b3a; border:1px solid #b7dfc4; border-radius:10px; padding:3px 9px; font-size:9pt; }
        QPushButton { background:#ffffff; border:1px solid #e2e3e6; border-radius:9px; padding:8px 14px; font-size:10pt; color:#2b2f36; }
        QPushButton:hover { background:#f5f7fa; border-color:#d5d9e0; }
        QPushButton:disabled { color:#b6bac1; background:#f7f7f6; border-color:#eeeeec; }
        #primarySideButton { text-align:left; background:#ffffff; border:1px solid #e3e4e7; border-radius:10px; padding:10px 13px; font-size:10.5pt; color:#2b2f36; }
        #primarySideButton:hover { background:#f4f8ff; border-color:#c9dbfb; color:#2458b8; }
        #sideAction { text-align:left; border:none; background:transparent; color:#5f646c; padding:8px 11px; border-radius:8px; }
        #sideAction:hover { background:#f0f1f3; color:#1b1e23; }
        #stageButton { text-align:left; border:none; background:transparent; color:#5f646c; padding:8px 11px; border-radius:8px; }
        #stageButton:hover { background:#f0f1f3; }
        #stageButton:disabled { color:#c5c8cd; background:transparent; }
        #tinyAction { border:none; background:transparent; color:#8f949c; padding:5px 7px; font-size:9pt; }
        #tinyAction:hover { color:#2458b8; background:#f1f5fd; border-radius:7px; }
        #headerAction { border:none; background:transparent; color:#8f949c; padding:6px 10px; border-radius:8px; }
        #headerAction:hover { color:#2458b8; background:#f1f5fd; }
        #sendButton { background:#2f6fe4; color:#ffffff; border:none; border-radius:10px; padding:9px 22px; font-weight:600; }
        #sendButton:hover { background:#2a63cc; }
        QTableWidget { background:#ffffff; border:1px solid #e6e5e2; border-radius:8px; alternate-background-color:#fbfbfa; gridline-color:#f0efec; }
        QHeaderView::section { background:#f7f7f5; color:#5b6068; padding:6px; border:none; border-right:1px solid #efeeec; border-bottom:1px solid #e6e5e2; font-size:9pt; font-weight:600; }
        QScrollBar:vertical { background:transparent; width:10px; margin:2px; }
        QScrollBar::handle:vertical { background:#dcdcd9; border-radius:5px; min-height:32px; }
        QScrollBar::handle:vertical:hover { background:#c9c9c5; }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background:transparent; }
        """)

    def append_chat(self, role, message):
        text = str(message)
        self.chat_history.append({"role": role, "content": text})
        self.conversation.append_message(role, text)

    _IMPORTANT_WORDS = ("失败", "错误", "不能", "冲突", "无效", "不存在", "无法")

    def notify(self, message):
        """操作反馈（选中行、布置元件、撤销……）只保留最新一条，避免连续操作刷屏。"""
        text = str(message)
        if not any(word in text for word in self._IMPORTANT_WORDS):
            if self.conversation.update_transient(text):
                if self.chat_history and self.chat_history[-1].get("transient"):
                    self.chat_history[-1]["content"] = text
                return
        self.chat_history.append({"role": "assistant", "content": text, "transient": True})
        self.conversation.append_message("assistant", text, transient=True)

    # ------------------------------------------------------------------ 启动流程
    def start_design(self):
        self.append_chat("user", "开始管束设计")
        self._boot_session()

    def _boot_session(self, product_id: str | None = None):
        try:
            products = self.repository.list_products(80)
        except DatabaseUnavailable as exc:
            self.append_chat(
                "assistant",
                "无法连接正式数据库，未生成任何草稿：\n"
                f"{exc}\n"
                "排查：1) 确认本机 MySQL 已启动并监听 3306；2) 账号密码与正式程序 "
                "modules/buguan/buguan_ziyong/database_utils.py 一致（默认 root/123456）；"
                "3) 确认存在“产品设计活动库”。修好后重新点“开始管束设计”。",
            )
            return
        if not products:
            self.append_chat("assistant", "正式数据库里还没有产品记录，请先在正式程序中创建产品。")
            return
        if product_id is None:
            product_id = products[0]["产品ID"]
        try:
            product = self.repository.product(product_id)
            upstream = self.repository.upstream(product_id)
            params = self.repository.layout_params(product_id)
            defaults = self.repository.layout_defaults(product["产品型式"])
            config_rows = self.repository.center_distance_table()
            sheet_rows = self.repository.sheet_form("a")
        except (DatabaseUnavailable, Exception) as exc:  # noqa: BLE001
            self.append_chat("assistant", f"读取正式数据库失败：{exc}\n未生成草稿，请检查数据库后重试。")
            return

        params = self._merge_defaults(params, defaults, upstream)
        self.session = DesignSession(self.repository, product, upstream, self)
        self.session.stage_changed.connect(self._on_stage_changed)
        self.pages.clear()
        self.conversation.remove_widget(self.card)
        self.card = None
        self.config_rows = config_rows
        self.sheet_rows = sheet_rows
        self.defaults = defaults
        self.chat_title.setText(self.session.header_text())

        # 管板型式页（含 R2 等结构尺寸）先建好，布管页才能拿到 DL 联动值
        sheet_page = self._build_sheet_page()
        self.pages[0] = sheet_page
        sheet_payload = sheet_page.to_payload()

        self._render_stage(0)
        summary = [
            f"已接入正式数据库：{self.session.header_text()}",
            f"项目ID {self.session.project_id or '（库中为空）'}，产品型式 {self.session.product_type}",
            f"布管参数：数据库已有 {len([v for v in params.values() if str(v.get('value', '')).strip()])} 项，"
            f"其余按 {product['产品型式']} 的正式默认表补齐",
            f"管板型式已按 {sheet_payload.get('管板类型', 'a')} 型生成，布管限定圆 DL="
            f"{sheet_payload.get('布管限定圆 DL')}",
        ]
        self.append_chat("assistant", "\n".join(summary) + "\n\n请先检查“管板型式”，保留后我会自动进入“布管”。")

    def _merge_defaults(self, params: dict, defaults: dict, upstream: dict) -> dict:
        merged: dict[str, dict] = {}
        for name, row in (params or {}).items():
            value = row.get("value")
            merged[name] = {
                "value": value,
                "unit": row.get("unit", ""),
                "source": "布管参数表" if str(value or "").strip() else "程序默认值",
            }
        for name, value in (defaults or {}).items():
            if name not in merged or not str(merged[name].get("value") or "").strip():
                merged[name] = {"value": value, "unit": merged.get(name, {}).get("unit", ""), "source": "程序默认值"}
        # 前序模块数据优先：公称直径、是否以外径为基准
        dn = upstream.get("公称直径") or upstream.get("公称直径 DN")
        if dn and str(dn.get("value", "")).strip():
            merged["公称直径 DN"] = {"value": str(dn["value"]).strip(), "unit": "mm", "source": "设计数据表"}
        basis = upstream.get("是否以外径为基准")
        if basis and str(basis.get("value", "")).strip() in {"是", "否"}:
            merged["是否以外径为基准"] = {"value": str(basis["value"]).strip(), "unit": "", "source": "通用数据表"}
        return merged

    # ------------------------------------------------------------------ 页面构建
    def _sheet_form_values(self) -> dict:
        page = self.pages.get(0)
        if isinstance(page, SheetFormStage):
            return {definition.name: definition.value for definition in page.defs}
        return {}

    def _build_sheet_page(self) -> SheetFormStage:
        existing = self.pages.get(0)
        if isinstance(existing, SheetFormStage):
            return existing
        page = SheetFormStage(
            self.repository, self.session.product_type, self.session.dn(),
        )
        page.keep_requested.connect(lambda: self.keep_current("管板型式"))
        page.parameters_changed.connect(lambda _values: self._on_stage_edited("管板型式"))
        return page

    def _build_layout_page(self) -> TubeLayoutPage:
        existing = self.pages.get(1)
        if isinstance(existing, TubeLayoutPage):
            return existing
        sheet_values = self._sheet_form_values()
        params = self._merge_defaults(
            self.repository.layout_params(self.session.product_id),
            self.defaults,
            self.session.upstream,
        )
        # 管板型式 → 布管：DL 由 DN 与 R2 决定
        if sheet_values:
            params.setdefault("布管限定圆 DL", {"value": "", "unit": "", "source": "联动计算"})
            params["布管限定圆 DL"]["value"] = self.session.layout_linkage(
                {"R2": sheet_values.get("R2", 8.0)}
            )["布管限定圆 DL"]
            params["布管限定圆 DL"]["source"] = "联动计算"
        page = TubeLayoutPage(
            params,
            self.session.product_type,
            self.defaults,
            center_distance_rows=self.config_rows,
            sheet_form=sheet_values,
        )
        page.headless = self.headless
        page.keep_requested.connect(lambda: self.keep_current("布管"))
        page.status_message.connect(self.notify)
        page.state_changed.connect(lambda _info: self._on_stage_edited("布管"))
        return page

    def _build_connection_page(self) -> TubeConnectionStage:
        existing = self.pages.get(2)
        if isinstance(existing, TubeConnectionStage):
            return existing
        page = TubeConnectionStage(self.repository)
        page.keep_requested.connect(lambda: self.keep_current("管-板连接"))
        page.parameters_changed.connect(lambda _values: self._on_stage_edited("管-板连接"))
        return page

    def _build_axial_page(self) -> AxialStage:
        existing = self.pages.get(3)
        if isinstance(existing, AxialStage):
            return existing
        layout_page = self.pages.get(1)
        length = 4500.0
        spacing = 200.0
        if isinstance(layout_page, TubeLayoutPage):
            try:
                length = float(layout_page.parameters["换热管公称长度 LN"]["value"])
            except (KeyError, TypeError, ValueError):
                pass
            try:
                spacing = float(layout_page.parameters["折流/支持板间距"]["value"])
            except (KeyError, TypeError, ValueError):
                pass
        connection = self.pages.get(2)
        thickness = 60.0
        if isinstance(connection, TubeConnectionStage):
            try:
                thickness = float(connection.values().get("管板厚度 δt", 60) or 60)
            except (TypeError, ValueError):
                pass
        page = AxialStage(length, spacing, thickness)
        page.keep_requested.connect(lambda: self.keep_current("轴向设计"))
        page.parameters_changed.connect(lambda _values: self._on_stage_edited("轴向设计"))
        return page

    def _ensure_page(self, index: int) -> QWidget:
        builders = {
            0: self._build_sheet_page,
            1: self._build_layout_page,
            2: self._build_connection_page,
            3: self._build_axial_page,
        }
        page = self.pages.get(index) or builders[index]()
        self.pages[index] = page
        if page.parent() is None:
            page.setParent(None)
        return page

    def _render_stage(self, index: int) -> None:
        if self.session is None:
            return
        self.conversation.remove_widget(self.card)
        self.card = None
        page = self._ensure_page(index)
        stage = STAGES[index]
        self.card = PreviewCard(stage, page, approved=self.session.approved[index])
        # 预览卡片高度锁定为聊天区可视高度：卡片一出现就占满，避免“保留”被挤出屏幕
        self.card.fit_to(max(self.conversation.viewport().height() - 12, 340))
        self.conversation.append_widget(self.card)
        self.conversation.scroll_to(self.card)
        QTimer.singleShot(80, self.conversation._scroll_to_bottom)
        self.session.current_index = index
        self._refresh_stage_buttons()

    def _on_stage_changed(self, index: int) -> None:
        self._refresh_stage_buttons()

    def _refresh_stage_buttons(self) -> None:
        if self.session is None:
            for button in self.stage_buttons:
                button.setEnabled(False)
                button.setStyleSheet("")
            return
        frontier = self.session.next_unapproved
        if frontier is None:
            frontier = len(STAGES)
        for index, button in enumerate(self.stage_buttons):
            button.setEnabled(index <= frontier)
            if index == self.session.current_index:
                button.setStyleSheet(
                    "background:#eaf1fe;color:#2458b8;border:none;border-radius:8px;"
                    "padding:8px 11px;font-weight:600;text-align:left;"
                )
            elif self.session.approved[index]:
                button.setStyleSheet(
                    "background:transparent;color:#256b3a;border:none;border-radius:8px;"
                    "padding:8px 11px;text-align:left;"
                )
            else:
                button.setStyleSheet(
                    "background:transparent;color:#5f646c;border:none;border-radius:8px;"
                    "padding:8px 11px;text-align:left;"
                )

    def open_stage(self, index: int) -> None:
        if self.session is None:
            self.append_chat("assistant", "请先点击“开始管束设计”。")
            return
        if index > 0 and not self.session.approved[index - 1]:
            self.append_chat("assistant", f"请先保留“{STAGES[index - 1]}”，再进入“{STAGES[index]}”。")
            return
        self._render_stage(index)

    def _on_stage_edited(self, stage: str) -> None:
        """已保留的 Tab 被修改 → 后续草稿作废并重算。"""
        if self.session is None:
            return
        index = STAGES.index(stage)
        if not self.session.approved[index]:
            return
        self.session.invalidate_from(stage)
        self.append_chat(
            "assistant",
            f"检测到“{stage}”已修改，后续 Tab 的草稿已自动作废，需要重新检查并保留。",
        )
        self._refresh_stage_buttons()

    # ------------------------------------------------------------------ 保留
    def keep_current(self, stage: str) -> None:
        if self.session is None:
            return
        index = STAGES.index(stage)
        page = self.pages.get(index)
        if page is None:
            return
        allowed, reason = self.session.can_keep(stage)
        if not allowed:
            if not self.headless:
                QMessageBox.information(self, "尚不能保留", reason)
            self.append_chat("assistant", reason)
            return
        issues = page.run_validation() if hasattr(page, "run_validation") else page.validate()
        if issues:
            if hasattr(page, "set_issues"):
                page.set_issues(issues)
            detail = "\n".join(
                f"• {item['field']}：{item['message']}"
                + (f"（推荐 {item['recommended']}）" if item.get("recommended") is not None else "")
                for item in issues
            )
            self.append_chat("assistant", f"“{stage}”有 {len(issues)} 项没通过校验，尚未写库：\n{detail}")
            return
        if not self.headless:
            answer = QMessageBox.question(
                self,
                "确认保留",
                f"确认保留“{stage}”的当前内容吗？\n保留后进入下一个 Tab；四个 Tab 全部保留才会写数据库。",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if answer != QMessageBox.Yes:
                return
        payload = page.to_payload()
        self.session.mark_kept(stage, payload)
        self.append_chat("assistant", f"已保留“{stage}”（尚未写库）。")
        self._sync_downstream(stage)
        if self.session.complete:
            self.final_save()
            return
        self._render_stage(self.session.current_index)

    def _sync_downstream(self, stage: str) -> None:
        if stage == "管板型式":
            layout_page = self.pages.get(1)
            if isinstance(layout_page, TubeLayoutPage):
                sheet_payload = self.session.payloads.get("管板型式", {})
                linkage = self.session.layout_linkage(sheet_payload)
                layout_page.sheet_form = {d.name: d.value for d in self.pages[0].defs}
                layout_page.set_parameter(
                    "布管限定圆 DL", linkage["布管限定圆 DL"], "联动计算", run_linkage=False
                )
                layout_page.recompute(reason="管板型式已保留，布管按新 DL 重算")
        elif stage == "布管":
            axial = self.pages.get(3)
            layout_payload = self.session.payloads.get("布管", {})
            if isinstance(axial, AxialStage):
                parameters = layout_payload.get("parameters", {})
                length = parameters.get("换热管公称长度 LN", {}).get("value", "")
                spacing = parameters.get("折流/支持板间距", {}).get("value", "")
                if length:
                    axial.set_value("换热管公称长度 LN", length)
                if spacing:
                    axial.set_value("折流板间距", spacing)

    def final_save(self) -> None:
        if self.session is None or not self.session.complete:
            return
        plan = self.session.preview_statements()
        head = [
            f"产品 {self.session.product_id}（{self.session.product_type}）四个 Tab 已全部保留。",
            "即将在单个事务中写入正式数据库：",
            "• 产品设计活动表_管板形式表",
            "• 产品设计活动表_布管参数表（65 项）",
            "• 产品设计活动表_布管元件表（拉杆/挡板/滑道等坐标）",
            "• 产品设计活动表_布管输入表 / 布管结果表",
            "• 产品设计活动表_布管数量表（水平或竖直 + 显示）",
            "• 产品设计活动表_管板连接表",
            f"共 {len(plan)} 条 SQL。失败会自动回滚。",
        ]
        if self.headless:
            # 自动验收/截图模式只展示计划，绝不写正式库
            self.append_chat(
                "assistant",
                "\n".join(head) + "\n\n（当前为自动验收模式，只生成写库计划，未提交到数据库。）",
            )
            return
        dialog = QMessageBox(self)
        dialog.setWindowTitle("写入正式数据库")
        dialog.setText("\n".join(head))
        dialog.setDetailedText("\n".join(plan[:80]))
        dialog.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
        dialog.button(QMessageBox.Ok).setText("确认写入")
        dialog.button(QMessageBox.Cancel).setText("暂不写入")
        if dialog.exec_() != QMessageBox.Ok:
            self.append_chat("assistant", "已取消写入，草稿仍保留在本次对话中，数据库未改变。")
            return
        try:
            result = self.session.save()
        except (SaveFailed, DatabaseUnavailable) as exc:
            self.append_chat(
                "assistant",
                f"写库失败，已回滚，数据库未产生部分写入：{exc}\n"
                "请检查数据库连接/表结构后重新点击“保留”所属流程，或联系管理员。",
            )
            return
        except Exception as exc:  # noqa: BLE001
            self.append_chat("assistant", f"写库异常并已回滚：{exc}")
            return
        self.append_chat(
            "assistant",
            f"已写入正式数据库：产品 {self.session.product_id}，执行 {result.get('statements')} 条语句，事务已提交。",
        )
        self._refresh_stage_buttons()

    # ------------------------------------------------------------------ 对话
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
            self.append_chat("assistant", "请先点击左侧“开始管束设计”，读取数据库并生成草稿后才能修改。")
            return
        if self._handle_local_command(text):
            return
        if self.config.configured:
            client = DeepSeekClient(self.config)
            # 状态提示（已选中第 N 行……）不进入模型上下文，避免占满 token
            history = [
                {"role": item["role"], "content": item["content"]}
                for item in self.chat_history[:-1]
                if not item.get("transient")
            ]
            context = self._ai_context()
            stage = self.session.current_stage
            self.send_button.setEnabled(False)
            self._start_worker(
                lambda: client.chat(history, context, stage, text),
                self._handle_ai_result,
            )
            return
        self.append_chat(
            "assistant",
            "离线模式只识别明确的操作（例如“换热管中心距改成34毫米”“重新布管，尽量多布”"
            "“外围对称布置8根拉杆”“保留当前方案”“把刚才的修改撤销”）。"
            "如需自由问答，请在 AI 设置中填写 DeepSeek API Key。",
        )

    def _ai_context(self) -> dict:
        context: dict[str, dict] = {}
        if self.session is None:
            return context
        for index, stage in enumerate(STAGES):
            page = self.pages.get(index)
            if page is None:
                continue
            if isinstance(page, TubeLayoutPage):
                context[stage] = {
                    name: {
                        "value": data.get("value"),
                        "unit": data.get("unit", ""),
                        "editable": name != "布管限定圆 DL",
                    }
                    for name, data in page.parameters.items()
                }
            else:
                context[stage] = {
                    definition.name: {
                        "value": definition.value,
                        "unit": definition.unit,
                        "editable": definition.kind != "readonly",
                    }
                    for definition in page.defs
                }
        return context

    # ---------------- 本地命令（不依赖 API Key）----------------
    def _handle_local_command(self, text: str) -> bool:
        page = self.pages.get(self.session.current_index) if self.session else None
        layout_page = self.pages.get(1)
        compact = re.sub(r"\s+", "", text)

        if any(word in compact for word in ("撤销", "撤回")):
            if isinstance(layout_page, TubeLayoutPage):
                layout_page.undo()
                self.append_chat("assistant", "已撤销上一步布管操作。")
            else:
                self.append_chat("assistant", "当前页没有可撤销的操作。")
            return True

        if compact in {"保留", "保留当前方案", "确认保留"} or "保留当前" in compact:
            self.keep_current(self.session.current_stage)
            return True

        if "使用推荐值" in compact or "采用推荐" in compact:
            if isinstance(page, TubeLayoutPage) and page.issues:
                issue = next((i for i in page.issues if i.get("recommended") is not None), None)
                if issue:
                    page.apply_recommendation(issue["field"], issue["recommended"])
                    self.append_chat("assistant", f"已采用推荐值：{issue['field']} = {issue['recommended']}。")
                    return True
            self.append_chat("assistant", "当前没有问题项需要采用推荐值。")
            return True

        if isinstance(layout_page, TubeLayoutPage):
            if any(word in compact for word in ("重新布管", "尽量多布", "多布")):
                target = None
                match = re.search(r"至少(\d+)根", compact)
                if match:
                    target = int(match.group(1))
                outcome = layout_page.max_tubes(target)
                if outcome.get("ok"):
                    self.append_chat(
                        "assistant",
                        f"已按正式程序布管接口重新计算：中心距 S={outcome['S']:g}，"
                        f"共 {outcome['count']} 个管孔。"
                        + ("已满足数量要求。" if target and outcome["count"] >= target else ""),
                    )
                else:
                    self.append_chat("assistant", outcome.get("message", "布管未成功。"))
                return True

            match = re.search(r"(?:外围|对称)?(?:布置|增加|加)?(\d+)根拉杆", compact)
            if match:
                count = int(match.group(1))
                added = layout_page.place_edge_rods(count)
                self.append_chat("assistant", f"已在外围对称布置 {added} 根拉杆，管孔数量已同步刷新。")
                return True

            match = re.search(r"(\d+)块旁路挡板", compact)
            if match:
                added = layout_page.place_bypasses(int(match.group(1)))
                self.append_chat("assistant", f"已沿壳体内壁布置 {added} 块旁路挡板。")
                return True

            if "防冲板" in compact and any(word in compact for word in ("上方", "顶部", "布置", "增加")):
                added = layout_page.place_impingement_top(1)
                self.append_chat("assistant", f"已在上方布置 {added} 块防冲板。")
                return True

        if "为什么" in compact and "不通过" in compact:
            issues = page.validation_issues() if hasattr(page, "validation_issues") else []
            if issues:
                detail = "\n".join(
                    f"• {item['field']}：{item['message']}"
                    + (f"（推荐 {item['recommended']}）" if item.get("recommended") is not None else "")
                    for item in issues
                )
                self.append_chat("assistant", f"当前不通过的原因：\n{detail}")
            else:
                self.append_chat("assistant", "当前页参数校验全部通过，没有阻塞项。")
            return True

        return self._handle_parameter_sentence(text)

    def _handle_parameter_sentence(self, text: str) -> bool:
        """把“换热管中心距改成34毫米”这类句子落到对应 Tab 的参数上。"""
        aliases: dict[str, list[str]] = {}
        for alias, canonical in FIELD_ALIASES.items():
            aliases.setdefault(canonical, []).append(alias)
        candidates: list[tuple[int, str, str, str]] = []
        for index, stage in enumerate(STAGES):
            page = self.pages.get(index)
            if page is None:
                continue
            if isinstance(page, TubeLayoutPage):
                for name in page.parameters:
                    names = [name] + aliases.get(name, [])
                    candidates.append((max(len(n) for n in names), stage, name, "layout"))
            else:
                for definition in page.defs:
                    names = [definition.name] + aliases.get(definition.name, [])
                    candidates.append((max(len(n) for n in names), stage, definition.name, "stage"))
        candidates.sort(reverse=True)
        for _length, stage, name, kind in candidates:
            matched = next((alias for alias in sorted([name] + aliases.get(name, []), key=len, reverse=True)
                            if alias and alias in text), None)
            if not matched:
                continue
            suffix = text.split(matched, 1)[1]
            page = self.pages.get(STAGES.index(stage))
            number = re.search(r"(-?\d+(?:\.\d+)?)", suffix)
            value = None
            if kind == "layout":
                options = self._layout_options(page, name)
                if options:
                    value = next((option for option in options if option in suffix), None)
                if value is None and number:
                    value = number.group(1)
            else:
                options = next((d.options for d in page.defs if d.name == name), ())
                if options:
                    value = next((option for option in options if option in suffix), None)
                if value is None and number:
                    value = number.group(1)
            if value is None:
                continue
            self._apply_parameter(stage, name, value)
            return True
        return False

    @staticmethod
    def _layout_options(page: TubeLayoutPage, name: str) -> tuple[str, ...]:
        from bundle.params import spec_for
        return spec_for(name, page.product_type, page.parameters).options

    def _apply_parameter(self, stage: str, name: str, value) -> None:
        page = self.pages.get(STAGES.index(stage))
        if isinstance(page, TubeLayoutPage):
            old = page.parameters.get(name, {}).get("value")
            changed = page.set_parameter(name, str(value), "AI 对话修改")
            page.recompute(reason=f"修改 {name}")
            self.append_chat(
                "assistant",
                f"已把“{stage}｜{name}”从 {old} 改为 {value}，并按正式程序接口重新布管"
                f"（当前 {len(page.current_centers())} 个管孔）。尚未写库。",
            )
        else:
            old = next((d.value for d in page.defs if d.name == name), None)
            page.set_value(name, value)
            page.refresh_preview()
            self.append_chat("assistant", f"已把“{stage}｜{name}”从 {old} 改为 {value}。尚未写库。")
        self._on_stage_edited(stage)

    # ---------------- 模型结果 ----------------
    def _handle_ai_result(self, result) -> None:
        if self.session is None:
            return
        result = result if isinstance(result, dict) else {}
        reply = str(result.get("reply", "")).strip()
        actions = result.get("actions", []) or []
        applied, rejected = [], []
        for action in actions:
            stage = str(action.get("stage", "")).strip()
            parameter = str(action.get("parameter", "")).strip()
            if stage not in STAGES or parameter not in CANONICAL_FIELDS.get(stage, set()):
                rejected.append(f"{stage}｜{parameter}：不属于该 Tab 的参数")
                continue
            page = self.pages.get(STAGES.index(stage))
            if page is None:
                rejected.append(f"{stage}｜{parameter}：该 Tab 尚未生成草稿")
                continue
            try:
                if isinstance(page, TubeLayoutPage):
                    page.set_parameter(parameter, action.get("value"), "AI 对话修改")
                    page.recompute(reason=f"修改 {parameter}")
                else:
                    page.set_value(parameter, action.get("value"))
                    page.refresh_preview()
                applied.append(f"{stage}｜{parameter} = {action.get('value')}")
                self._on_stage_edited(stage)
            except Exception as exc:  # noqa: BLE001
                rejected.append(f"{stage}｜{parameter}：{exc}")
        lines = [reply or "我已检查这条要求。"]
        if applied:
            lines.append("\n已更新草稿（未写库）：")
            lines.extend(f"• {item}" for item in applied)
        if rejected:
            lines.append("\n未执行：")
            lines.extend(f"• {item}" for item in rejected)
        self.append_chat("assistant", "\n".join(lines))

    def _start_worker(self, fn, callback):
        self._worker_cancelled = False
        self._worker_callback = callback
        self.worker = TaskThread(fn, self)
        self.worker.result_ready.connect(self._worker_result)
        self.worker.failed.connect(self._worker_error)
        self.worker.finished.connect(self._worker_finished)
        self.worker.start()

    def _worker_result(self, result):
        if not self._worker_cancelled and self._worker_callback:
            self._worker_callback(result)

    def _worker_error(self, message):
        if self._worker_cancelled:
            return
        self.append_chat("assistant", f"这条要求没处理成功：{message}\n参数没有被修改，重新发送一次即可。")

    def _worker_finished(self):
        self.send_button.setEnabled(True)
        if self.worker is not None:
            self.worker.deleteLater()
        self.worker = None
        self._worker_callback = None

    # ------------------------------------------------------------------ 其他
    def open_settings(self):
        self.config = settings_dialog(self, self.config)
        self._refresh_model_label()
        self.append_chat("assistant", "AI 设置已更新。" if self.config.configured else "当前为离线模式。")

    def open_product_list(self):
        try:
            products = self.repository.list_products(80)
        except DatabaseUnavailable as exc:
            self.append_chat("assistant", f"读取产品列表失败：{exc}")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("选择产品（正式数据库）")
        dialog.resize(720, 480)
        layout = QVBoxLayout(dialog)
        listing = QListWidget()
        for product in products:
            listing.addItem(
                f"{product['产品ID']}  {product['产品型式']}  {product['产品类型']}"
            )
            listing.item(listing.count() - 1).setData(Qt.UserRole, product["产品ID"])
        layout.addWidget(listing)
        buttons = QHBoxLayout()
        buttons.addStretch()
        confirm = QPushButton("载入该产品")
        cancel = QPushButton("关闭")
        buttons.addWidget(confirm)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)
        if products:
            listing.setCurrentRow(0)

        def choose():
            item = listing.currentItem()
            if item is None:
                return
            dialog.accept()
            self._boot_session(item.data(Qt.UserRole))

        confirm.clicked.connect(choose)
        cancel.clicked.connect(dialog.reject)
        dialog.exec_()

    def clear_chat(self):
        if self.worker is not None and self.worker.isRunning():
            self.append_chat("assistant", "当前要求仍在处理中，完成后再新建对话。")
            return
        self.conversation.clear()
        self.chat_history = []
        self.card = None
        self.pages.clear()
        self.session = None
        self._refresh_stage_buttons()
        self.append_chat("assistant", "对话已清空。点击左侧“开始管束设计”重新读取数据库。")

    def closeEvent(self, event):
        if self.worker is not None and self.worker.isRunning():
            self.worker.requestInterruption()
            self._worker_cancelled = True
            event.ignore()
            return
        super().closeEvent(event)
