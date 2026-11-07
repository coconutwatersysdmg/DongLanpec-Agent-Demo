# -*- coding: utf-8 -*-
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication

from ai_support.api_client import APIConfig, DeepSeekClient
from bundle.placement import HoleOp
from window import DesignWindow


class _OfflineRepository:
    allow_write = False

    def ping(self):
        return False, "offline"


class AgentRoutingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = DesignWindow(repository=_OfflineRepository())
        self.window.session = SimpleNamespace(current_stage="布管")
        self.window.config = SimpleNamespace(configured=True)
        self.window._ai_context = Mock(return_value={})
        self.window._layout_state = Mock(return_value={})
        self.window._start_worker = Mock()

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()

    def test_configured_agent_receives_open_ended_hole_request_before_local_rules(self):
        self.window._handle_local_command = Mock(return_value=True)
        self.window.prompt.setPlainText("删除最外层换热管")

        self.window.send_note()

        self.window._handle_local_command.assert_not_called()
        self.window._start_worker.assert_called_once()

    def test_explicit_confirmation_remains_an_immediate_local_control(self):
        self.window._handle_local_command = Mock(return_value=True)
        self.window.prompt.setPlainText("确认方案")

        self.window.send_note()

        self.window._handle_local_command.assert_called_once_with("确认方案")
        self.window._start_worker.assert_not_called()

    def test_agent_receives_real_plan_view_in_sanitized_context(self):
        client = DeepSeekClient(APIConfig(api_key="secret"))
        client._complete_json = Mock(return_value={"reply": "需要确认", "actions": []})

        client.chat([], {}, "布管", "删除边缘管", {"plan_view": "行+3 |o o|"})

        user_payload = json.loads(client._complete_json.call_args.args[1])
        self.assertEqual(user_payload["layout_state"]["plan_view"], "行+3 |o o|")

    def test_agent_prompt_allows_bulk_outline_rods_without_artificial_limit(self):
        client = DeepSeekClient(APIConfig(api_key="secret"))
        client._complete_json = Mock(return_value={"reply": "已生成方案", "placements": []})

        client.chat([], {}, "布管", "将最外轮廓换热管都变为拉杆", {"plan_view": "84 根"})

        system_prompt = client._complete_json.call_args.args[0]
        self.assertNotIn("单次最多 40 根", system_prompt)
        self.assertIn('region:"outline"', system_prompt)

    def test_model_selected_tubes_survive_until_preview_card(self):
        self.window._show_hole_card = Mock()
        self.window._parse_hole_words = Mock(return_value=HoleOp(region="outline"))
        result = {
            "reply": "我根据当前布管图选出了两根管。",
            "actions": [],
            "placements": [],
            "hole_ops": [{
                "op": "delete",
                "region": "selected",
                "tubes": [{"row": 3, "col": -2}, {"row": 3, "col": 2}],
            }],
            "ui_actions": [],
        }

        self.window._handle_ai_result(result)

        ops = self.window._show_hole_card.call_args.args[0]
        self.assertEqual(ops[0].tubes, [(3, -2), (3, 2)])
        self.window._parse_hole_words.assert_not_called()

    def test_model_question_does_not_create_a_hardcoded_fallback_plan(self):
        self.window._show_hole_card = Mock()
        self.window._parse_hole_words = Mock(return_value=HoleOp(region="outline"))

        self.window._handle_ai_result({
            "reply": "你说的最外层是整圈，还是只删除上下两排？",
            "actions": [], "placements": [], "hole_ops": [], "ui_actions": [],
        })

        self.window._show_hole_card.assert_not_called()
        self.window._parse_hole_words.assert_not_called()


if __name__ == "__main__":
    unittest.main()
