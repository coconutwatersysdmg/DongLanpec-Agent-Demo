import unittest

from bundle import params


class ParamTableTests(unittest.TestCase):
    def test_param_order_matches_formal_program(self):
        self.assertEqual(len(params.PARAM_ORDER), 65)
        self.assertEqual(len(set(params.PARAM_ORDER)), 65)
        self.assertEqual(params.PARAM_ORDER[0], "是否以外径为基准")

    def test_control_kinds_follow_formal_program(self):
        kinds = {}
        sample = {"管程程数": {"value": "2"}, "管程分程形式": {"value": "2.1"}}
        for name in params.PARAM_ORDER:
            spec = params.spec_for(name, "AEU", sample)
            kinds[spec.kind] = kinds.get(spec.kind, 0) + 1
            if spec.kind in {"combo", "pattern"}:
                self.assertTrue(spec.options, f"{name} 是普通下拉框但缺少选项")
            if spec.kind == "combo_edit":
                self.assertTrue(spec.options, f"{name} 可输入下拉框缺少候选值")
        self.assertGreaterEqual(kinds.get("combo", 0) + kinds.get("pattern", 0), 5)
        self.assertGreaterEqual(kinds.get("number", 0), 10)
        self.assertGreaterEqual(kinds.get("combo_edit", 0), 1)

    def test_recommend_placeholder_exists(self):
        placeholders = [
            name for name in params.PARAM_ORDER
            if "程序推荐" in params.spec_for(name, "AEU", {"管程程数": {"value": "2"}}).options
        ]
        self.assertTrue(placeholders, "至少应有“程序推荐”可输入项（如隔条位置尺寸 W）")

    def test_derived_field_is_readonly(self):
        spec = params.spec_for("布管限定圆 DL", "AEU", {})
        self.assertTrue(spec.readonly, "布管限定圆 DL 由联动计算，必须只读")
        self.assertIn("布管限定圆 DL", params.DERIVED_FIELDS)

    def test_tube_pass_and_pattern_options(self):
        self.assertEqual(params.tube_pass_options("AEU"), ("2", "4", "6", "8", "10", "12"))
        self.assertIn("1", params.tube_pass_options("固定管板"))
        options = params.tube_pattern_options("2")
        self.assertIn("2.1", options)

    def test_lb_mapping_covers_dll_keys(self):
        self.assertIn("公称直径 DN", params.LB_MAPPING)
        self.assertIn("布管限定圆 DL", params.LB_MAPPING)


if __name__ == "__main__":
    unittest.main()
