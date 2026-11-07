# -*- coding: utf-8 -*-
import json
import unittest
from unittest.mock import Mock

from ai_support.api_client import APIConfig, DeepSeekClient
from bundle import page


def _envelope(content: str) -> bytes:
    return json.dumps({
        "choices": [{"message": {"content": content}, "finish_reason": "stop"}]
    }, ensure_ascii=False).encode("utf-8")


class AgentContextRecoveryTests(unittest.TestCase):
    def test_malformed_structured_reply_is_retried_once_with_same_request(self):
        client = DeepSeekClient(APIConfig(api_key="secret"))
        client._send = Mock(side_effect=[
            _envelope("我明白了，你指的是折流板。"),
            _envelope('{"reply":"明白了，是折流板。","placements":['
                      '{"kind":"baffle","count":1,"region":"any","options":{}}]}'),
        ])

        result = client._complete_json("system", "保留上一轮上下文：哦我是说折流板")

        self.assertEqual(result["placements"][0]["kind"], "baffle")
        self.assertEqual(client._send.call_count, 2)

    def test_clarification_turn_keeps_recent_dialogue(self):
        client = DeepSeekClient(APIConfig(api_key="secret"))
        client._complete_json = Mock(return_value={"reply": "明白了", "placements": []})
        history = [
            {"role": "user", "content": "为什么图中没有绘制防冲板"},
            {"role": "assistant", "content": "当前没有防冲板。"},
        ]

        client.chat(history, {}, "布管", "哦我是说折流板", {})

        payload = json.loads(client._complete_json.call_args.args[1])
        self.assertEqual(payload["recent_dialogue"], history)
        self.assertEqual(payload["user_message"], "哦我是说折流板")


class BaffleChordTests(unittest.TestCase):
    def test_single_bow_horizontal_draws_two_yellow_chords_like_formal_program(self):
        specs = page.baffle_chord_specs({
            "折流板类型": {"value": "单弓形"},
            "折流板切口方向": {"value": "水平上下"},
            "折流板要求切口率": {"value": "20"},
        }, radius=100.0)

        self.assertEqual(len(specs), 2)
        self.assertTrue(all(item["orientation"] == "horizontal" for item in specs))
        self.assertEqual({round(item["level"], 6) for item in specs}, {-60.0, 60.0})
        self.assertTrue(all(round(item["half_length"], 6) == 80.0 for item in specs))
        self.assertTrue(all(item["color"] == (204, 204, 0) for item in specs))

    def test_double_bow_vertical_draws_a_blue_and_b_red_chords(self):
        specs = page.baffle_chord_specs({
            "折流板类型": {"value": "双弓形"},
            "折流板切口方向": {"value": "垂直左右"},
            "A型板切口与中心线间距a": {"value": "30"},
            "B型板切口与中心线间距b": {"value": "50"},
        }, radius=100.0)

        self.assertEqual(len(specs), 4)
        self.assertTrue(all(item["orientation"] == "vertical" for item in specs))
        self.assertEqual([(item["tag"], item["color"]) for item in specs], [
            ("A", (150, 200, 255)), ("A", (150, 200, 255)),
            ("B", (255, 150, 150)), ("B", (255, 150, 150)),
        ])

    def test_support_plate_has_no_cut_chords(self):
        specs = page.baffle_chord_specs({
            "折流板类型": {"value": "支持板"},
            "折流板切口方向": {"value": "水平上下"},
            "折流板要求切口率": {"value": "20"},
        }, radius=100.0)
        self.assertEqual(specs, [])


if __name__ == "__main__":
    unittest.main()
