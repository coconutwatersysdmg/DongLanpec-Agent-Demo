import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PyQt5.QtWidgets import QApplication

from ai_support.api_client import parse_fact_payload
from demo_db import DemoRepository
from document_reader import DocumentBundle, DocumentPart, DocumentRecord, retrieve
from pipeline import TubeBundleAgent
from review_session import ReviewSession
from rules import validate_stage
from window import DesignWindow


class ReviewerRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = DemoRepository(Path(self.tmp.name) / "demo.sqlite3")

    def tearDown(self):
        self.repo.close()
        self.tmp.cleanup()

    def prepared(self, proposals=None, conflicts=None):
        design = self.repo.create_design("OST-E-1904A", "AEU", 700)
        return SimpleNamespace(
            design_id=design["id"], version=design["version"],
            base_context=self.repo.load_base_context("AEU", 700),
            evidence=[], history=self.repo.lookup_history("AEU", 700),
            proposals=proposals or [], conflicts=conflicts or [],
        )

    def test_retrieval_excludes_untagged_continuations_and_other_equipment_text(self):
        bundle = DocumentBundle([DocumentRecord("mix", "已解析", "hash", [
            DocumentPart("data.pdf", "data.pdf 第1页", "OST-E-1904A outside diameter 25 mm. OST-E-1903A outside diameter 19 mm."),
            DocumentPart("reply.xlsx", "reply.xlsx 第2行", "outside diameter 19 mm continued"),
            DocumentPart("common.pdf", "common.pdf 第1页", "通用要求：所有换热器均采用强度焊"),
        ])])
        evidence = retrieve(bundle, "OST-E-1904A", ["outside", "强度焊"], 20)
        text = "\n".join(item.excerpt for item in evidence)
        self.assertIn("OST-E-1904A", text)
        self.assertNotIn("OST-E-1903A", text)
        self.assertNotIn("continued", text)
        self.assertIn("通用要求", text)

    def test_layout_tube_length_propagates_to_axial_validation(self):
        session = ReviewSession(self.prepared(), self.repo)
        session.apply_edit("换热管公称长度 LN", 1000, stage="布管与元件")
        self.assertEqual(session.parameters["轴向设计"]["换热管公称长度 LN"]["value"], 1000)
        session.current_stage_index = 3
        session.apply_edit("伸出管板长度 L_ext", 2000)
        self.assertFalse(session.run_review().passed)

    def test_nonfinite_and_fractional_integer_values_are_rejected(self):
        params = self.repo.load_base_context("AEU", 700)["布管与元件"]
        for bad in (float("nan"), float("inf"), 2.5):
            params["管程程数"]["value"] = bad
            result = validate_stage("布管与元件", params)
            self.assertFalse(result.passed, bad)
            self.assertTrue(any(i.field == "管程程数" for i in result.issues))

    def test_negative_weld_dimensions_fail_and_coverage_is_visible(self):
        params = self.repo.load_base_context("AEU", 700)["管-板连接"]
        params["坡口长度 lgroove"]["value"] = -100
        result = validate_stage("管-板连接", params)
        self.assertFalse(result.passed)
        self.assertTrue(any(i.field == "坡口长度 lgroove" for i in result.issues))
        self.assertTrue(result.coverage_warnings)

    def test_model_aliases_and_separate_tube_counts_are_canonicalized(self):
        parsed = parse_fact_payload({"facts": [
            {"stage": "布管与元件", "parameter": "换热管外径", "value": 25, "unit": "mm", "evidence": "OD25", "source_ref": "p1", "assertion_type": "requirement"},
            {"stage": "布管与元件", "parameter": "U型管根数", "value": 675, "unit": "根", "evidence": "675", "source_ref": "p2", "assertion_type": "confirmed"},
            {"stage": "布管与元件", "parameter": "管孔数量", "value": 1350, "unit": "个", "evidence": "1350", "source_ref": "p2", "assertion_type": "confirmed"},
            {"stage": "布管与元件", "parameter": "不存在的参数", "value": 1, "evidence": "x", "source_ref": "p3", "assertion_type": "confirmed"},
        ]})
        names = [item["parameter"] for item in parsed["facts"]]
        self.assertEqual(names, ["换热管外径 do", "U形管根数", "管孔数"])
        self.assertEqual(parsed["conflicts"][0]["assertion_type"], "unsupported")

    def test_competing_model_values_require_visible_human_disposition(self):
        proposals = [
            {"stage": "布管与元件", "parameter": "换热管外径 do", "value": 19, "unit": "mm", "evidence": "19", "source_ref": "old", "source": "文件明确要求"},
            {"stage": "布管与元件", "parameter": "换热管外径 do", "value": 25, "unit": "mm", "evidence": "25", "source_ref": "new", "source": "文件明确要求"},
        ]
        session = ReviewSession(self.prepared(proposals=proposals), self.repo)
        session.current_stage_index = 1
        result = session.run_review()
        self.assertFalse(result.passed)
        self.assertTrue(any("冲突" in i.message for i in result.issues))
        session.apply_edit("换热管外径 do", 25)
        self.assertTrue(session.run_review().passed)

    def test_source_inventory_is_saved_with_hash(self):
        bundle = DocumentBundle([DocumentRecord("spec.pdf", "已解析", "abc123", [
            DocumentPart("spec.pdf", "spec.pdf 第1页", "OST-E-1904A tube 25")
        ])])
        prepared = TubeBundleAgent(self.repo).prepare_design(bundle, "OST-E-1904A", "BES", 700)
        rows = self.repo.list_sources(prepared.design_id)
        self.assertEqual(rows[0]["file_name"], "spec.pdf")
        self.assertEqual(rows[0]["file_hash"], "abc123")

    def test_history_is_same_type_only_and_can_be_cloned_as_new_version(self):
        self.assertEqual(self.repo.lookup_history("NEN", 700), [])
        session = ReviewSession(self.prepared(), self.repo)
        for _ in range(4):
            session.run_review()
            session.confirm_and_advance()
        snapshot = self.repo.load_design_snapshot(session.design_id)
        clone = self.repo.clone_design(session.design_id)
        self.assertEqual(snapshot["design"]["status"], "已完成")
        self.assertEqual(clone["status"], "审核中")
        self.assertNotEqual(clone["id"], session.design_id)

    def test_gui_database_failure_is_readable_and_retryable(self):
        window = DesignWindow(repository=self.repo)
        window.start_with_bundle(DocumentBundle([]), "E-1001", "AEU", 700)
        window.run_review()
        with patch.object(self.repo, "save_stage", side_effect=sqlite3.OperationalError("disk full")), patch("window.QMessageBox.warning"):
            window.confirm_and_next()
        self.assertIn("保存失败", window.issue_text.toPlainText())
        self.assertTrue(window.confirm_button.isEnabled())
        window.close()

    def test_ui_exposes_stop_and_previous_stage_controls(self):
        window = DesignWindow(repository=self.repo)
        self.assertTrue(hasattr(window, "stop_button"))
        self.assertTrue(hasattr(window, "previous_button"))
        window.close()


if __name__ == "__main__":
    unittest.main()
