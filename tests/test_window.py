import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PyQt5.QtGui import QColor
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

    def test_start_design_uses_hidden_demo_context_and_opens_real_preview(self):
        fresh = DesignWindow(repository=self.repo)
        fresh.config = APIConfig(api_key="")
        try:
            fresh.start_demo_design()
            self.assertIsNotNone(fresh.session)
            self.assertEqual(fresh.prepared.base_context["管板型式"]["产品型式"]["value"], "AEU")
            self.assertFalse(fresh.review_panel.isHidden())
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

    def test_prepared_design_opens_review_drawer_when_user_action_is_needed(self):
        self.assertFalse(self.window.review_panel.isHidden())
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

    def test_codex_style_layout_is_wide_with_fixed_sidebar_and_inline_preview(self):
        self.assertGreaterEqual(self.window.width(), 1760)
        self.assertGreaterEqual(self.window.height(), 1040)
        self.assertGreaterEqual(self.window.sidebar.minimumWidth(), 340)
        self.assertEqual(self.window.sidebar.maximumWidth(), self.window.sidebar.minimumWidth())
        self.assertIs(self.window.review_panel.parentWidget(), self.window.main_panel)
        self.assertEqual(self.window.findChildren(QSplitter), [])

    def test_preview_table_uses_readable_codex_scale(self):
        self.assertGreaterEqual(self.window.parameter_table.font().pixelSize(), 16)
        self.assertGreaterEqual(self.window.parameter_table.verticalHeader().defaultSectionSize(), 44)
        self.assertGreaterEqual(self.window.parameter_table.horizontalHeader().height(), 44)

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
