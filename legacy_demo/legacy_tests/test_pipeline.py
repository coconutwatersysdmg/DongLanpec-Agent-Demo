import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_support.api_client import APIConfig, DeepSeekClient, parse_chat_payload, parse_fact_payload
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

    def test_chat_payload_normalizes_actions_and_rejects_unknown_or_duplicate_fields(self):
        parsed = parse_chat_payload({
            "reply": "已经按你的要求调整。",
            "actions": [
                {"stage": "布管与元件", "parameter": "换热管中心距", "value": 34},
                {"stage": "轴向设计", "parameter": "折流板间距", "value": 500},
                {"stage": "轴向设计", "parameter": "折流板间距", "value": 600},
                {"stage": "不存在阶段", "parameter": "未知参数", "value": 1},
            ],
        })
        self.assertEqual(parsed["reply"], "已经按你的要求调整。")
        self.assertEqual(parsed["actions"], [
            {"stage": "布管与元件", "parameter": "换热管中心距 S", "value": 34},
            {"stage": "轴向设计", "parameter": "折流板间距", "value": 500},
        ])
        self.assertEqual(len(parsed["rejected"]), 2)

    def test_chat_request_keeps_api_key_out_of_model_payload(self):
        response_body = json.dumps({
            "choices": [{"message": {"content": json.dumps({"reply": "好的", "actions": []}, ensure_ascii=False)}}]
        }).encode("utf-8")

        class FakeResponse:
            def __enter__(self):
                return self
            def __exit__(self, *_args):
                return False
            def read(self):
                return response_body

        captured = {}
        def fake_urlopen(req, timeout):
            captured["request"] = req
            captured["timeout"] = timeout
            return FakeResponse()

        client = DeepSeekClient(APIConfig(api_key="super-secret-key"))
        context = {"管板型式": {"R1": {"value": 12, "editable": True, "derived": False}}}
        with patch("ai_support.api_client.request.urlopen", side_effect=fake_urlopen):
            result = client.chat(
                [{"role": "user", "content": "你好"}], context, "管板型式", "R1 改成 13"
            )

        request_body = captured["request"].data.decode("utf-8")
        self.assertNotIn("super-secret-key", request_body)
        self.assertIn("Bearer super-secret-key", captured["request"].headers["Authorization"])
        self.assertEqual(result["reply"], "好的")


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
