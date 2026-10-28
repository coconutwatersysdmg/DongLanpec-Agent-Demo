import tempfile
import unittest
from pathlib import Path

from demo_db import DemoRepository
from document_reader import DocumentBundle
from pipeline import TubeBundleAgent
from review_session import ReviewSession


class ReviewSessionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = DemoRepository(Path(self.tmp.name) / "demo.sqlite3")
        prepared = TubeBundleAgent(self.repo).prepare_design(DocumentBundle([]), "E-1001", "AEU", 700)
        self.session = ReviewSession(prepared, self.repo)

    def tearDown(self):
        self.repo.close()
        self.tmp.cleanup()

    def test_edit_requires_review_and_failed_issue_has_recommendation(self):
        self.session.current_stage_index = 1
        self.session.apply_edit("换热管中心距 S", 20)
        self.assertEqual(self.session.status, "待审核")
        result = self.session.run_review()
        self.assertFalse(result.passed)
        self.assertEqual(self.session.status, "审核不通过")
        issue = next(i for i in result.issues if i.field == "换热管中心距 S")
        self.assertEqual(issue.recommended, 32.0)

    def test_missing_file_component_data_uses_clearly_labelled_history_suggestion(self):
        row = self.session.parameters["布管与元件"]["拉杆数量"]
        self.assertEqual(row["source"], "历史建议值")
        self.assertIn("H-AEU-0700-01", row["evidence"])

    def test_one_click_recommendation_still_requires_review_again(self):
        self.session.current_stage_index = 1
        self.session.apply_edit("换热管中心距 S", 20)
        result = self.session.run_review()
        issue = next(i for i in result.issues if i.field == "换热管中心距 S")
        self.session.apply_recommendation(issue.issue_id)
        self.assertEqual(self.session.current_parameters["换热管中心距 S"]["value"], 32.0)
        self.assertEqual(self.session.status, "待审核")
        with self.assertRaises(ValueError):
            self.session.confirm_and_advance()
        self.assertTrue(self.session.run_review().passed)

    def test_review_pass_does_not_save_until_user_confirms(self):
        result = self.session.run_review()
        self.assertTrue(result.passed)
        self.assertIsNone(self.repo.load_stage(self.session.design_id, "管板型式"))
        self.session.confirm_and_advance()
        self.assertIsNotNone(self.repo.load_stage(self.session.design_id, "管板型式"))
        self.assertEqual(self.session.current_stage, "布管与元件")

    def test_four_confirmed_stages_finalize_independent_design(self):
        for _ in range(4):
            self.assertTrue(self.session.run_review().passed)
            self.session.confirm_and_advance()
        design = self.repo.get_design(self.session.design_id)
        self.assertEqual(self.session.status, "已完成")
        self.assertEqual(design["status"], "已完成")
        for stage in ("管板型式", "布管与元件", "管-板连接", "轴向设计"):
            self.assertEqual(self.repo.load_stage(self.session.design_id, stage)["review_status"], "用户确认")

    def test_editing_upstream_invalidates_downstream_approvals(self):
        for _ in range(3):
            self.assertTrue(self.session.run_review().passed)
            self.session.confirm_and_advance()
        self.assertEqual(self.session.approved[:3], [True, True, True])
        self.session.apply_edit("R2", 14, stage="管板型式")
        self.assertEqual(self.session.approved, [False, False, False, False])
        self.assertIsNone(self.repo.load_stage(self.session.design_id, "管-板连接"))


if __name__ == "__main__":
    unittest.main()
