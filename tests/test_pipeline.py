import json
import tempfile
import unittest
from pathlib import Path

from ai_support.api_client import APIConfig, DeepSeekClient, parse_fact_payload
from demo_db import DemoRepository
from document_reader import DocumentBundle, DocumentPart, DocumentRecord
from pipeline import TubeBundleAgent


class DeepSeekClientTests(unittest.TestCase):
    def test_default_endpoint_and_model_are_deepseek_v4_flash(self):
        config = APIConfig(api_key="secret")
        self.assertEqual(config.model, "deepseek-v4-flash")
        self.assertEqual(config.endpoint(), "https://api.deepseek.com/chat/completions")

    def test_non_deepseek_host_is_rejected(self):
        with self.assertRaises(ValueError):
            APIConfig(base_url="https://example.com", api_key="x").endpoint()

    def test_questions_are_not_returned_as_facts(self):
        parsed = parse_fact_payload({"facts": [
            {"stage": "布管与元件", "parameter": "折流板形式", "value": "单弓形", "assertion_type": "question", "evidence": "单弓形还是双弓形？", "source_ref": "reply.xlsx"},
            {"stage": "管-板连接", "parameter": "管板连接方式", "value": "强度焊＋贴胀", "assertion_type": "requirement", "evidence": "采用强度焊+贴胀", "source_ref": "spec.pdf"},
        ]})
        self.assertEqual(len(parsed["facts"]), 1)
        self.assertEqual(parsed["facts"][0]["parameter"], "管板连接方式")
        self.assertEqual(len(parsed["conflicts"]), 1)


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = DemoRepository(Path(self.tmp.name) / "demo.sqlite3")
        parts = [
            DocumentPart("spec.pdf", "spec.pdf 第2页", "OST-E-1904A shall use strength welding plus expansion"),
            DocumentPart("reply.xlsx", "reply.xlsx 工作表“答复”第3行", "OST-E-1904A should baffle be single or double?"),
            DocumentPart("other.pdf", "other.pdf 第1页", "OST-E-1903A outside diameter 19 mm"),
        ]
        self.bundle = DocumentBundle([DocumentRecord("mixed", "已解析", "abc", parts)])

    def tearDown(self):
        self.repo.close()
        self.tmp.cleanup()

    def test_offline_pipeline_is_honest_and_keeps_history_as_suggestion(self):
        result = TubeBundleAgent(self.repo, client=None).prepare_design(
            self.bundle, "OST-E-1904A", "BES", 700
        )
        self.assertTrue(any("未调用" in row["message"] for row in result.trace))
        self.assertEqual(result.base_context["管板型式"]["公称直径 DN"]["source"], "模拟上游数据")
        self.assertEqual(result.history[0]["source"], "历史建议值")
        self.assertFalse(result.proposals)

    def test_model_proposals_do_not_silently_replace_base_values(self):
        class FakeClient:
            configured = True
            def extract_facts(self, evidence, equipment_id):
                return {"facts": [{"stage": "布管与元件", "parameter": "换热管外径 do", "value": 25, "unit": "mm", "evidence": "OD25", "source_ref": "spec.pdf", "assertion_type": "requirement"}], "conflicts": []}
        result = TubeBundleAgent(self.repo, FakeClient()).prepare_design(self.bundle, "OST-E-1904A", "BES", 700)
        self.assertEqual(result.base_context["布管与元件"]["换热管外径 do"]["source"], "程序默认值")
        self.assertEqual(result.proposals[0]["source"], "文件明确要求")


if __name__ == "__main__":
    unittest.main()
