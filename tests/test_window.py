import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest

from PyQt5.QtCore import QCoreApplication, QEvent, Qt
from PyQt5.QtGui import QFontMetrics, QTextCursor
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QLabel, QPushButton

from db.production import DatabaseUnavailable
from bundle.page import TubeLayoutPage
from models import STAGES
from session import DesignSession
from bundle.stages import AxialStage, SheetFormStage, TubeConnectionStage
from window import DesignWindow, MessageInput, PlanParamField


class OfflineRepository:
    """模拟数据库不可用：用于验证“明确报错、不退回模拟库”。"""

    allow_write = False

    def ping(self):
        return False, "无法连接 MySQL：Can't connect to MySQL server on 'localhost' (10061)"

    def list_products(self, limit=80):
        raise DatabaseUnavailable("无法连接正式数据库：Can't connect to MySQL server")


class SuccessfulRepository:
    """最小成功数据源：用来验证启动成功后不在对话里输出冗长摘要。"""

    allow_write = False

    def ping(self):
        return True, "已连接"

    def list_products(self, limit=80):
        return [{"产品ID": "P1", "项目ID": "J1", "产品型式": "BEM"}]

    def product(self, product_id):
        return {"产品ID": product_id, "项目ID": "J1", "产品型式": "BEM"}

    def upstream(self, product_id):
        return {"公称直径": {"value": "1000"}}

    def layout_params(self, product_id):
        return {}

    def layout_defaults(self, product_type):
        return {}

    def center_distance_table(self):
        return []

    def sheet_form(self, letter):
        return []


class WindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = DesignWindow(repository=OfflineRepository())
        self.window.resize(1600, 960)
        self.window.show()

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        # 只清理 Qt 的延迟销毁，不在 tearDown 中执行定时器/普通事件。
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def test_stage_buttons_use_formal_names(self):
        labels = [button.text() for button in self.window.stage_buttons]
        self.assertEqual(tuple(labels), STAGES)
        self.assertTrue(all(not button.isEnabled() for button in self.window.stage_buttons))

    def test_all_tabs_are_available_once_design_session_exists(self):
        self.window.session = DesignSession(
            self.window.repository,
            {"产品ID": "P1", "项目ID": "J1", "产品型式": "AEU"},
            {"公称直径": {"value": "1000"}},
        )

        self.window._refresh_stage_buttons()

        self.assertTrue(all(button.isEnabled() for button in self.window.stage_buttons))

    def test_opening_later_tab_does_not_require_previous_tab_kept(self):
        self.window.session = DesignSession(
            self.window.repository,
            {"产品ID": "P1", "项目ID": "J1", "产品型式": "AEU"},
            {"公称直径": {"value": "1000"}},
        )
        self.window.pages[3] = QLabel("轴向设计草稿")

        self.window.open_stage(3)

        self.assertEqual(self.window.session.current_index, 3)
        self.assertIsNotNone(self.window.card)

    def test_initial_screen_is_chat_style(self):
        self.assertEqual(len(self.window.chat_history), 1)
        self.assertEqual(self.window.chat_history[0]["role"], "assistant")
        self.assertTrue(self.window.prompt.isVisible() or self.window.prompt is not None)

    def test_sidebar_uses_ai_agent_brand_without_demo_wording(self):
        labels = [label.text() for label in self.window.sidebar.findChildren(QLabel)]
        self.assertIn("AI AGENT", labels)
        self.assertNotIn("Agent Demo", labels)
        self.assertEqual(self.window.windowTitle(), "管束设计 AI AGENT")

    def test_successful_start_does_not_append_database_summary(self):
        window = DesignWindow(repository=SuccessfulRepository())
        self.addCleanup(window.deleteLater)
        before = len(window.chat_history)

        window._boot_session()

        self.assertIsNotNone(window.session)
        self.assertEqual(len(window.chat_history), before)

    def test_sheet_form_and_connection_render_in_chat_without_top_preview(self):
        self.window.session = DesignSession(
            self.window.repository,
            {"产品ID": "P1", "项目ID": "J1", "产品型式": "AEU"},
            {"公称直径": {"value": "1000"}},
        )
        self.window.pages[0] = SheetFormStage(None, "AEU", 1000)
        self.window.pages[2] = TubeConnectionStage(None)

        for index in (0, 2):
            self.window._render_stage(index)
            self.assertTrue(self.window.preview_host.isHidden())
            self.assertIsNotNone(self.window.inline_card)
            self.assertIn(self.window.inline_card, self.window.conversation.message_rows)

    def test_layout_and_axial_keep_the_top_graphical_preview(self):
        self.window.session = DesignSession(
            self.window.repository,
            {"产品ID": "P1", "项目ID": "J1", "产品型式": "AEU"},
            {"公称直径": {"value": "1000"}},
        )
        self.window.pages[1] = QLabel("布管图形")
        self.window.pages[3] = QLabel("轴向图形")

        for index in (1, 3):
            self.window._render_stage(index)
            self.assertFalse(self.window.preview_host.isHidden())
            self.assertIsNotNone(self.window.card)
            self.assertIsNone(self.window.inline_card)

    def test_connection_selectors_are_not_repeated_as_parameter_rows(self):
        page = TubeConnectionStage(None)
        row_names = [
            page.table.item(row, 1).text()
            for row in range(page.table.rowCount())
            if page.table.item(row, 1) is not None
        ]
        self.assertNotIn("管板连接方式", row_names)
        self.assertNotIn("管板类型", row_names)
        self.assertEqual(set(page.selector_editors), {"管板连接方式", "管板类型"})

    def test_connection_plate_type_uses_source_program_names_not_database_codes(self):
        page = TubeConnectionStage(None, plate_type="0")
        selector = page.selector_editors["管板类型"]
        self.assertEqual(selector.currentText(), "整体管板")
        self.assertEqual(page.to_payload()["管板类型"], "0")

        selector.setCurrentText("复合管板")
        page._on_edited("管板类型")

        self.assertEqual(page.to_payload()["管板类型"], "1")

    def test_sheet_form_type_follows_product_type_rules(self):
        fixed_types = {
            "AES": "a",
            "BES": "a",
            "AKU": "a",
            "BKU": "a",
            "NEN": "b",
            "NEN(H)": "b",
            "AEM": "e",
            "BEM": "e",
        }
        for product_type, expected in fixed_types.items():
            with self.subTest(product_type=product_type):
                page = SheetFormStage(None, product_type, 1000)
                selector = page.selector_editors["管板类型"]
                self.assertEqual(page.letter, expected)
                self.assertEqual(selector.currentText(), expected)
                self.assertFalse(selector.isEnabled())
                page.load_form("f")
                self.assertEqual(page.letter, expected)
                self.assertEqual(page.to_payload()["管板类型"], expected)

        for product_type in ("AEU", "BEU", "OTHER"):
            with self.subTest(product_type=product_type):
                page = SheetFormStage(None, product_type, 1000)
                selector = page.selector_editors["管板类型"]
                self.assertEqual(page.letter, "a")
                self.assertTrue(selector.isEnabled())
                selector.setCurrentText("f")
                page._on_edited("管板类型")
                self.assertEqual(page.letter, "f")
                self.assertEqual(page.to_payload()["管板类型"], "f")

    def test_sheet_and_connection_stages_show_their_original_diagrams(self):
        pages = (SheetFormStage(None, "AEU", 1000), TubeConnectionStage(None))
        for page in pages:
            with self.subTest(stage=page.TITLE):
                page.resize(1200, 700)

                self.assertFalse(page.preview_panel.isHidden())
                self.assertIsNotNone(page._pixmap)
                self.assertFalse(page._pixmap.isNull())

    def test_sheet_form_hides_duplicate_inner_title(self):
        page = SheetFormStage(None, "AEU", 1000)

        self.assertNotIn(
            "管板型式",
            [label.text() for label in page.findChildren(QLabel)],
        )

    def test_connection_and_axial_stages_hide_duplicate_titles_and_hints(self):
        pages = (TubeConnectionStage(None), AxialStage())
        for page in pages:
            with self.subTest(stage=page.TITLE):
                labels = [label.text() for label in page.findChildren(QLabel)]
                self.assertNotIn(page.TITLE, labels)
                self.assertFalse(page.hint_label.isVisible())

    def test_sheet_form_shows_only_source_parameters_but_keeps_derived_dl(self):
        page = SheetFormStage(None, "AEU", 1000)
        row_names = [
            page.table.item(row, 1).text()
            for row in range(page.table.rowCount())
            if page.table.item(row, 1) is not None
        ]
        payload = page.to_payload()

        self.assertNotIn("产品型式", row_names)
        self.assertNotIn("公称直径 DN", row_names)
        self.assertNotIn("布管限定圆 DL", row_names)
        self.assertEqual(row_names, ["R1", "R2", "h", "α", "ρ", "e"])
        self.assertEqual(payload["布管限定圆 DL"], 984)
        self.assertNotIn("布管限定圆 DL", payload["parameters"])

    def test_stage_parameter_table_displays_all_rows_without_vertical_scrollbar(self):
        pages = (SheetFormStage(None, "AEU", 1000), TubeConnectionStage(None))
        for page in pages:
            with self.subTest(stage=page.TITLE):
                header_height = page.table.horizontalHeader().sizeHint().height()
                desired_height = (
                    page.table.rowCount()
                    * page.table.verticalHeader().defaultSectionSize()
                    + header_height
                    + 4
                )
                self.assertEqual(
                    page.table.verticalScrollBarPolicy(), Qt.ScrollBarAlwaysOff
                )
                self.assertGreaterEqual(page.table.minimumHeight(), desired_height)

    def test_stage_unit_column_fits_all_unit_text(self):
        pages = (SheetFormStage(None, "AEU", 1000), TubeConnectionStage(None))
        for page in pages:
            with self.subTest(stage=page.TITLE):
                page.resize(1200, 700)

                metrics = QFontMetrics(page.table.font())
                longest_unit = max(
                    (
                        metrics.horizontalAdvance(page.table.item(row, 3).text())
                        for row in range(page.table.rowCount())
                        if page.table.item(row, 3) is not None
                    ),
                    default=0,
                )
                self.assertGreaterEqual(page.table.columnWidth(3), max(56, longest_unit + 8))

    def test_keep_outputs_only_data_saved_success(self):
        self.window.headless = True
        self.window.session = DesignSession(
            self.window.repository,
            {"产品ID": "P1", "项目ID": "J1", "产品型式": "AEU"},
            {"公称直径": {"value": "1000"}},
        )
        self.window.pages[0] = SheetFormStage(None, "AEU", 1000)
        self.window.pages[1] = QLabel("布管图形")

        self.window.keep_current("管板型式")

        self.assertEqual(self.window.chat_history[-1]["content"], "数据保存成功")

    def test_keep_does_not_emit_linkage_status_before_success(self):
        window = DesignWindow(repository=SuccessfulRepository())
        self.addCleanup(window.deleteLater)
        window.headless = True
        window._boot_session()
        window.pages[1] = window._build_layout_page()
        before = len(window.chat_history)

        window.keep_current("管板型式")

        self.assertEqual(len(window.chat_history), before + 1)
        self.assertEqual(window.chat_history[-1]["content"], "数据保存成功")

    def test_user_message_is_right_aligned(self):
        self.window.append_chat("user", "换热管中心距改成34毫米")
        row = self.window.conversation.message_rows[-1]
        layout = row.layout()
        last_index = layout.count() - 1
        # 用户消息在右侧：右侧是消息本体
        self.assertEqual(layout.itemAt(last_index).widget().objectName(), "userMessage")

    def test_start_without_database_reports_error_instead_of_falling_back(self):
        self.window.start_design()
        last = self.window.chat_history[-1]
        self.assertEqual(last["role"], "assistant")
        self.assertIn("无法连接正式数据库", last["content"])
        self.assertIn("排查", last["content"])
        self.assertIsNone(self.window.session, "数据库失败时不得生成模拟草稿")

    def test_enter_sends_and_shift_enter_breaks_line(self):
        prompt = MessageInput()
        sent = []
        prompt.send_requested.connect(lambda: sent.append(prompt.toPlainText()))
        prompt.setPlainText("保留当前方案")
        QTest.keyClick(prompt, Qt.Key_Return)
        self.assertEqual(sent, ["保留当前方案"])

        prompt.moveCursor(QTextCursor.End)
        before = prompt.toPlainText()
        QTest.keyClick(prompt, Qt.Key_Return, Qt.ShiftModifier)
        self.assertEqual(prompt.toPlainText(), before + "\n")

    def test_enter_in_window_sends_chat_message(self):
        window = self.window
        window.prompt.setPlainText("保留当前方案")
        QTest.keyClick(window.prompt, Qt.Key_Return)
        self.assertEqual(window.prompt.toPlainText(), "", "发送后输入框应清空")
        self.assertEqual(window.chat_history[-2]["role"], "user")
        self.assertEqual(window.chat_history[-2]["content"], "保留当前方案")

    def test_clear_chat_keeps_greeting(self):
        self.window.append_chat("user", "你好")
        self.window.clear_chat()
        self.assertEqual(len(self.window.chat_history), 1)
        self.assertEqual(self.window.chat_history[0]["role"], "assistant")

    def test_plan_form_combo_is_wide_enough_for_full_option(self):
        field = PlanParamField({
            "name": "拉杆形式",
            "short": "形式",
            "kind": "choice",
            "options": ["螺纹拉杆", "焊接拉杆"],
            "value": "螺纹拉杆",
            "form": True,
        }, parent=self.window)
        combo = field.editor
        widest = max(combo.fontMetrics().horizontalAdvance(combo.itemText(i))
                     for i in range(combo.count()))
        # 右对齐 lineEdit、下拉箭头和样式内边距都要留空间；否则会从左边裁掉“螺”。
        self.assertGreaterEqual(combo.minimumWidth(), widest + 72)

    def test_layout_fullscreen_uses_the_whole_preview_pane_for_the_graph(self):
        page = TubeLayoutPage({}, "AEU", {}, parent=self.window)
        page.resize(1200, 600)
        self.window.preview_host.show()
        page.pane_fullscreen_requested.connect(self.window.set_preview_pane_fullscreen)

        page.toggle_fullscreen()

        self.assertFalse(self.window.isFullScreen(), "不应把整个主窗口切换为系统全屏")
        self.assertTrue(page.graphics_expanded)
        self.assertTrue(page.left_frame.isHidden())
        self.assertTrue(page.right_frame.isHidden())
        self.assertFalse(page.center_frame.isHidden())
        self.assertTrue(self.window.conversation.isHidden())
        self.assertTrue(self.window.composer_wrap.isHidden())
        self.assertEqual(page.fullscreen_button.text(), "退出全屏")

        page.toggle_fullscreen()

        self.assertFalse(page.graphics_expanded)
        self.assertFalse(page.left_frame.isHidden())
        self.assertFalse(page.right_frame.isHidden())
        self.assertFalse(self.window.conversation.isHidden())
        self.assertFalse(self.window.composer_wrap.isHidden())
        self.assertEqual(page.fullscreen_button.text(), "全屏")

    def test_layout_parameter_table_keeps_sequence_and_unit_columns_readable(self):
        page = TubeLayoutPage({}, "AEU", {})
        page.param_table.resize(620, 400)

        page.restore_param_table_column_widths()

        widths = [page.param_table.columnWidth(index) for index in range(4)]
        unit_width = max(
            (
                QFontMetrics(page.param_table.font()).horizontalAdvance(
                    page.param_table.item(row, 3).text()
                ) + 28
                for row in range(page.param_table.rowCount())
                if page.param_table.item(row, 3) is not None
                and page.param_table.item(row, 3).text()
            ),
            default=56,
        )
        self.assertGreaterEqual(widths[0], 48)
        self.assertGreaterEqual(widths[1], 120)
        self.assertGreaterEqual(widths[2], 180)
        self.assertGreaterEqual(widths[3], unit_width)

    def test_layout_action_bar_does_not_show_redundant_redraw_button(self):
        page = TubeLayoutPage({}, "AEU", {})
        button_texts = [button.text() for button in page.findChildren(QPushButton)]

        self.assertNotIn("重绘", button_texts)
        self.assertIn("撤销", button_texts)
        self.assertIn("全屏", button_texts)

    def test_switching_stage_exits_preview_pane_fullscreen_cleanly(self):
        self.window.session = DesignSession(
            self.window.repository,
            {"产品ID": "P1", "项目ID": "J1", "产品型式": "AEU"},
            {"公称直径": {"value": "1000"}},
        )
        page = TubeLayoutPage({}, "AEU", {})
        page.pane_fullscreen_requested.connect(self.window.set_preview_pane_fullscreen)
        self.window.pages[1] = page
        self.window.pages[3] = QLabel("轴向设计")
        self.window._render_stage(1)
        page.toggle_fullscreen()

        self.window.open_stage(3)

        self.assertFalse(self.window._preview_pane_fullscreen)
        self.assertFalse(page.graphics_expanded)
        self.assertEqual(page.fullscreen_button.text(), "全屏")
        self.assertFalse(self.window.conversation.isHidden())
        self.assertFalse(self.window.composer_wrap.isHidden())


if __name__ == "__main__":
    unittest.main()
