import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PyQt5.QtGui import QColor
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication, QComboBox, QDoubleSpinBox, QGraphicsView, QMessageBox, QSplitter, QTabWidget

from ai_support.api_client import APIConfig
from demo_db import DemoRepository
from document_reader import DocumentBundle
from window import DesignWindow


class WindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = DemoRepository(Path(self.tmp.name) / "demo.sqlite3")
        self.window = DesignWindow(repository=self.repo)
        self.window.start_with_bundle(DocumentBundle([]), "E-1001", "AEU", 700)

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        self.repo.close()
        self.tmp.cleanup()

    def value_row(self, field):
        for row in range(self.window.parameter_table.rowCount()):
            if self.window.parameter_table.item(row, 0).text() == field:
                return row
        self.fail(f"missing field {field}")

    def test_new_window_starts_with_chat_only_and_review_drawer_hidden(self):
        fresh = DesignWindow(repository=self.repo)
        try:
            self.assertTrue(fresh.review_panel.isHidden())
            self.assertFalse(fresh.review_toggle_button.isEnabled())
        finally:
            fresh.close()
            fresh.deleteLater()

    def test_main_window_requires_no_manual_context_inputs(self):
        fresh = DesignWindow(repository=self.repo)
        try:
            self.assertEqual(fresh.findChildren(QComboBox), [])
            self.assertEqual(fresh.findChildren(QDoubleSpinBox), [])
            self.assertEqual(fresh.start_design_button.text(), "开始管束设计")
        finally:
            fresh.close()
            fresh.deleteLater()

    def test_start_design_uses_hidden_demo_context_and_keeps_chat_primary(self):
        fresh = DesignWindow(repository=self.repo)
        fresh.config = APIConfig(api_key="")
        try:
            fresh.start_demo_design()
            self.assertIsNotNone(fresh.session)
            self.assertEqual(fresh.prepared.base_context["管板型式"]["产品型式"]["value"], "AEU")
            self.assertTrue(fresh.review_panel.isHidden())
            self.assertTrue(fresh.review_toggle_button.isEnabled())
            self.assertGreater(fresh.parameter_table.rowCount(), 5)
        finally:
            fresh.close()
            fresh.deleteLater()

    def test_chat_request_updates_preview_and_requires_review(self):
        self.window.session.current_stage_index = 1
        self.window.render_stage()
        changed = self.window.apply_chat_request("换热管中心距 S 改为 34")
        self.assertTrue(changed)
        self.assertEqual(self.window.session.current_parameters["换热管中心距 S"]["value"], 34)
        self.assertEqual(self.window.session.status, "待审核")
        self.assertTrue(self.window.save_button.isEnabled())

    def test_prepared_design_keeps_review_drawer_collapsed_until_requested(self):
        self.assertTrue(self.window.review_panel.isHidden())
        self.assertTrue(self.window.review_toggle_button.isEnabled())

    def test_collapsed_review_drawer_can_be_reopened_from_header(self):
        self.window.set_review_drawer_visible(False)
        self.assertTrue(self.window.review_panel.isHidden())
        self.window.review_toggle_button.click()
        self.assertFalse(self.window.review_panel.isHidden())

    def test_single_window_has_no_drawing_canvas_or_tab_widget(self):
        self.assertEqual(self.window.findChildren(QGraphicsView), [])
        self.assertEqual(self.window.findChildren(QTabWidget), [])
        self.assertIn("管板型式", self.window.stage_title.text())
        self.assertGreater(self.window.parameter_table.rowCount(), 5)

    def test_codex_style_layout_uses_normal_desktop_size_and_fixed_sidebar(self):
        self.assertEqual(self.window.size().width(), 1440)
        self.assertEqual(self.window.size().height(), 900)
        self.assertGreaterEqual(self.window.sidebar.minimumWidth(), 300)
        self.assertLessEqual(self.window.sidebar.minimumWidth(), 320)
        self.assertEqual(self.window.sidebar.maximumWidth(), self.window.sidebar.minimumWidth())
        self.assertIs(self.window.review_panel.parentWidget(), self.window.main_panel)
        self.assertEqual(self.window.findChildren(QSplitter), [])
        self.assertEqual(self.window.new_chat_button.text(), "新建对话")
        self.assertEqual(self.window.clear_chat_button.text(), "清空对话")
        self.assertLessEqual(self.window.prompt.minimumHeight(), 72)

    def test_window_uses_codex_like_chinese_ui_font(self):
        self.assertEqual(self.window.font().family(), "Microsoft YaHei UI")
        self.assertEqual(self.window.parameter_table.font().family(), "Microsoft YaHei UI")

    def test_preview_table_uses_readable_codex_scale(self):
        self.assertGreaterEqual(self.window.parameter_table.font().pointSize(), 10)
        self.assertGreaterEqual(self.window.parameter_table.verticalHeader().defaultSectionSize(), 40)
        self.assertGreaterEqual(self.window.parameter_table.horizontalHeader().height(), 40)

    def test_tube_sheet_type_uses_source_dropdown_options(self):
        row = self.value_row("管板类型")
        combo = self.window.parameter_table.cellWidget(row, 1)
        self.assertIsInstance(combo, QComboBox)
        self.assertFalse(combo.isEditable())
        self.assertEqual([combo.itemText(i) for i in range(combo.count())], list("abcdef"))

    def test_piping_stage_uses_source_editor_types_and_options(self):
        self.window.session.current_stage_index = 1
        self.window.render_stage()

        pass_combo = self.window.parameter_table.cellWidget(self.value_row("管程程数"), 1)
        self.assertIsInstance(pass_combo, QComboBox)
        self.assertFalse(pass_combo.isEditable())
        self.assertEqual(
            [pass_combo.itemText(i) for i in range(pass_combo.count())],
            ["2", "4", "6", "8", "10", "12"],
        )

        diameter_combo = self.window.parameter_table.cellWidget(self.value_row("换热管外径 do"), 1)
        self.assertIsInstance(diameter_combo, QComboBox)
        self.assertTrue(diameter_combo.isEditable())
        self.assertIn("25", [diameter_combo.itemText(i) for i in range(diameter_combo.count())])

        length_combo = self.window.parameter_table.cellWidget(self.value_row("换热管公称长度 LN"), 1)
        self.assertIsInstance(length_combo, QComboBox)
        self.assertTrue(length_combo.isEditable())
        self.assertIn("4500", [length_combo.itemText(i) for i in range(length_combo.count())])

        plain_row = self.value_row("旁路挡板宽度")
        self.assertIsNone(self.window.parameter_table.cellWidget(plain_row, 1))
        self.assertTrue(self.window.parameter_table.item(plain_row, 1).flags() & Qt.ItemIsEditable)

    def test_combo_edit_updates_review_session(self):
        self.window.session.current_stage_index = 1
        self.window.render_stage()
        row = self.value_row("换热管布置方式")
        combo = self.window.parameter_table.cellWidget(row, 1)
        combo.setCurrentText("跨中")
        combo.activated[str].emit("跨中")
        self.assertEqual(self.window.session.current_parameters["换热管布置方式"]["value"], "跨中")
        self.assertEqual(self.window.parameter_table.item(row, 1).text(), "跨中")

    def test_rerender_replaces_combo_widgets_instead_of_stacking_them(self):
        self.window.session.current_stage_index = 1
        self.window.render_stage()
        first = self.window.parameter_table.cellWidget(self.value_row("管程程数"), 1)
        self.window.render_stage()
        second = self.window.parameter_table.cellWidget(self.value_row("管程程数"), 1)
        self.assertIsNot(first, second)
        self.assertIsInstance(second, QComboBox)

    def test_offline_chat_can_immediately_modify_future_stage_draft(self):
        self.window.config = APIConfig(api_key="")
        self.window.prompt.setPlainText("折流板间距改成 500")
        self.window.send_note()

        self.assertEqual(self.window.session.current_stage, "管板型式")
        self.assertEqual(self.window.session.parameters["轴向设计"]["折流板间距"]["value"], 500)
        transcript = self.window.conversation.toPlainText()
        self.assertIn("轴向设计", transcript)
        self.assertIn("折流板间距", transcript)
        self.assertIn("450.0 → 500", transcript)

    def test_structured_chat_result_reports_applied_and_rejected_actions(self):
        self.window.handle_chat_result({
            "reply": "我检查了这两个要求。",
            "actions": [
                {"stage": "布管与元件", "parameter": "旁路挡板数量", "value": 3},
                {"stage": "管板型式", "parameter": "产品型式", "value": "BEU"},
            ],
            "rejected": [{"stage": "不存在", "parameter": "未知", "value": 1, "reason": "未知设计阶段"}],
        })

        transcript = self.window.conversation.toPlainText()
        self.assertIn("我检查了这两个要求", transcript)
        self.assertIn("旁路挡板数量", transcript)
        self.assertIn("2 → 3", transcript)
        self.assertIn("只读", transcript)
        self.assertIn("未知设计阶段", transcript)
        self.assertEqual(self.window.session.parameters["布管与元件"]["旁路挡板数量"]["value"], 3)
        self.assertEqual(self.window.session.parameters["管板型式"]["产品型式"]["value"], "AEU")

    def test_configured_chat_starts_background_request_and_blocks_duplicate_send(self):
        self.window.config = APIConfig(api_key="secret")
        self.window.prompt.setPlainText("帮我看看当前参数是否合理")
        with patch.object(self.window, "_start_worker") as start_worker:
            self.window.send_note()
        start_worker.assert_called_once()
        self.assertFalse(self.window.send_button.isEnabled())

    def test_clear_chat_keeps_design_draft_but_resets_transcript(self):
        design_id = self.window.session.design_id
        self.window.append_chat("user", "临时消息")
        self.window.clear_chat()
        self.assertEqual(self.window.session.design_id, design_id)
        self.assertNotIn("临时消息", self.window.conversation.toPlainText())
        self.assertIn("继续描述", self.window.conversation.toPlainText())

    def test_preview_exposes_one_save_action(self):
        self.assertEqual(self.window.save_button.text(), "保留")
        self.assertEqual(self.window.review_actions.count(), 2)  # button plus trailing stretch

    def test_save_with_invalid_value_marks_error_without_confirmation_or_database_write(self):
        self.window.session.current_stage_index = 1
        self.window.render_stage()
        row = self.value_row("换热管中心距 S")
        self.window.parameter_table.item(row, 1).setText("20")

        with patch.object(QMessageBox, "question") as question:
            self.window.save_current_stage()

        question.assert_not_called()
        self.assertEqual(
            self.window.parameter_table.item(row, 1).background().color(),
            QColor("#ffe0e0"),
        )
        self.assertIsNone(self.repo.load_stage(self.window.session.design_id, "布管与元件"))
        self.assertEqual(self.window.session.current_stage, "布管与元件")

    def test_save_confirmation_writes_stage_and_advances(self):
        with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
            self.window.save_current_stage()

        self.assertIsNotNone(self.repo.load_stage(self.window.session.design_id, "管板型式"))
        self.assertEqual(self.window.session.current_stage, "布管与元件")

    def test_cancel_save_confirmation_keeps_stage_unsaved(self):
        with patch.object(QMessageBox, "question", return_value=QMessageBox.No):
            self.window.save_current_stage()

        self.assertIsNone(self.repo.load_stage(self.window.session.design_id, "管板型式"))
        self.assertEqual(self.window.session.current_stage, "管板型式")

    def test_saved_stage_can_be_reopened_from_sidebar(self):
        with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
            self.window.save_current_stage()

        self.window.stage_buttons[0].click()

        self.assertEqual(self.window.session.current_stage, "管板型式")
        self.assertIn("管板型式", self.window.stage_title.text())

    def test_unreached_stages_are_disabled_in_sidebar(self):
        with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
            self.window.save_current_stage()

        self.assertTrue(self.window.stage_buttons[0].isEnabled())
        self.assertTrue(self.window.stage_buttons[1].isEnabled())
        self.assertFalse(self.window.stage_buttons[2].isEnabled())
        self.assertFalse(self.window.stage_buttons[3].isEnabled())

    def test_editing_reopened_stage_invalidates_it_and_downstream_snapshots(self):
        with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
            self.window.save_current_stage()
            self.window.save_current_stage()
        self.assertIsNotNone(self.repo.load_stage(self.window.session.design_id, "管板型式"))
        self.assertIsNotNone(self.repo.load_stage(self.window.session.design_id, "布管与元件"))

        self.window.open_stage(0)
        row = self.value_row("R1")
        self.window.parameter_table.item(row, 1).setText("13")

        self.assertIsNone(self.repo.load_stage(self.window.session.design_id, "管板型式"))
        self.assertIsNone(self.repo.load_stage(self.window.session.design_id, "布管与元件"))
        self.assertEqual(self.window.session.current_stage, "管板型式")

    def test_failed_cell_is_red_and_shows_reason_and_recommendation(self):
        self.window.session.current_stage_index = 1
        self.window.render_stage()
        row = self.value_row("换热管中心距 S")
        self.window.parameter_table.item(row, 1).setText("20")
        self.window.save_current_stage()
        color = self.window.parameter_table.item(row, 1).background().color()
        self.assertEqual(color, QColor("#ffe0e0"))
        self.assertIn("必须大于换热管外径", self.window.issue_text.toPlainText())
        self.assertGreater(len(self.window.recommendation_buttons), 0)
        self.assertTrue(self.window.save_button.isEnabled())

    def test_one_click_recommendation_requires_review_again(self):
        self.window.session.current_stage_index = 1
        self.window.render_stage()
        row = self.value_row("换热管中心距 S")
        self.window.parameter_table.item(row, 1).setText("20")
        self.window.save_current_stage()
        button = next(b for b in self.window.recommendation_buttons if "32" in b.text())
        button.click()
        self.assertEqual(self.window.parameter_table.item(row, 1).text(), "32.0")
        self.assertEqual(self.window.session.status, "待审核")
        with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
            self.window.save_current_stage()
        self.assertIsNotNone(self.repo.load_stage(self.window.session.design_id, "布管与元件"))

    def test_completed_design_keeps_reachable_stage_preview_available(self):
        with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
            for _ in range(4):
                self.window.save_current_stage()
        self.assertFalse(self.window.review_panel.isHidden())
        self.assertTrue(all(button.isEnabled() for button in self.window.stage_buttons))
        self.window.stage_buttons[0].click()
        self.assertEqual(self.window.session.current_stage, "管板型式")


if __name__ == "__main__":
    unittest.main()
