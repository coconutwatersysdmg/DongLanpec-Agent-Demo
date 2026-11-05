import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from demo_db import DemoRepository, VersionConflict


class DemoRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "demo.sqlite3"
        self.repo = DemoRepository(self.path)

    def tearDown(self):
        self.repo.close()
        self.tmp.cleanup()

    def test_base_context_has_four_stages_and_source_labels(self):
        context = self.repo.load_base_context("AEU", 700)
        self.assertEqual(set(context), {"管板型式", "布管与元件", "管-板连接", "轴向设计"})
        self.assertEqual(context["管板型式"]["产品型式"]["value"], "AEU")
        self.assertEqual(context["管板型式"]["公称直径 DN"]["source"], "模拟上游数据")
        self.assertEqual(context["布管与元件"]["换热管中心距 S"]["source"], "程序默认值")

    def test_history_ranks_same_type_then_nearest_dn(self):
        rows = self.repo.lookup_history("AEU", 710)
        self.assertGreaterEqual(len(rows), 2)
        self.assertEqual(rows[0]["product_type"], "AEU")
        self.assertEqual(rows[0]["dn"], 700)
        self.assertEqual(rows[0]["source"], "历史建议值")

    def test_save_stage_uses_optimistic_version(self):
        design = self.repo.create_design("OST-E-1904A", "BES", 700)
        version = self.repo.save_stage(design["id"], "管板型式", {"parameters": {"x": 1}}, design["version"])
        self.assertEqual(version, 2)
        with self.assertRaises(VersionConflict):
            self.repo.save_stage(design["id"], "布管与元件", {"parameters": {}}, design["version"])

    def test_finalize_rolls_back_when_a_stage_is_missing(self):
        design = self.repo.create_design("E-1001", "AEU", 700)
        version = design["version"]
        for stage in ("管板型式", "布管与元件", "管-板连接"):
            version = self.repo.save_stage(design["id"], stage, {"parameters": {}}, version)
        with self.assertRaises(ValueError):
            self.repo.finalize_design(design["id"], version)
        row = self.repo.get_design(design["id"])
        self.assertEqual(row["status"], "审核中")
        self.assertEqual(row["version"], version)

    def test_confirmed_stage_payload_is_persisted_with_evidence_excerpt(self):
        design = self.repo.create_design("E-1002", "AEU", 1300)
        payload = {
            "parameters": {"换热管外径 do": {"value": 25, "source": "文件明确要求"}},
            "evidence": [{"source_ref": "data.pdf 第4页", "excerpt": "换热管外径25mm"}],
        }
        self.repo.save_stage(design["id"], "布管与元件", payload, design["version"])
        saved = self.repo.load_stage(design["id"], "布管与元件")
        self.assertEqual(saved["parameters"]["换热管外径 do"]["value"], 25)
        self.assertEqual(saved["evidence"][0]["excerpt"], "换热管外径25mm")


if __name__ == "__main__":
    unittest.main()
