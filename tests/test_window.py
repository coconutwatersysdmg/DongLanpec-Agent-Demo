import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
import unittest
from pathlib import Path

from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import QApplication, QGraphicsView, QTabWidget

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

    def test_failed_cell_is_red_and_shows_reason_and_recommendation(self):
        self.window.session.current_stage_index = 1
        self.window.render_stage()
        row = self.value_row("换热管中心距 S")
        self.window.parameter_table.item(row, 1).setText("20")
        self.window.run_review()
        color = self.window.parameter_table.item(row, 1).background().color()
        self.assertEqual(color, QColor("#ffe0e0"))
        self.assertIn("必须大于换热管外径", self.window.issue_text.toPlainText())
        self.assertGreater(len(self.window.recommendation_buttons), 0)
        self.assertFalse(self.window.confirm_button.isEnabled())

    def test_one_click_recommendation_requires_review_again(self):
        self.window.session.current_stage_index = 1
        self.window.render_stage()
        row = self.value_row("换热管中心距 S")
        self.window.parameter_table.item(row, 1).setText("20")
        self.window.run_review()
        button = next(b for b in self.window.recommendation_buttons if "32" in b.text())
        button.click()
        self.assertEqual(self.window.parameter_table.item(row, 1).text(), "32.0")
        self.assertIn("请再次审核", self.window.review_status.text())
        self.assertFalse(self.window.confirm_button.isEnabled())
        self.window.run_review()
        self.assertTrue(self.window.confirm_button.isEnabled())

    def test_review_pass_stays_unsaved_until_separate_confirmation(self):
        self.window.run_review()
        self.assertTrue(self.window.confirm_button.isEnabled())
        self.assertIsNone(self.repo.load_stage(self.window.session.design_id, "管板型式"))
        self.window.confirm_and_next()
        self.assertIsNotNone(self.repo.load_stage(self.window.session.design_id, "管板型式"))
        self.assertIn("布管与元件", self.window.stage_title.text())


if __name__ == "__main__":
    unittest.main()
