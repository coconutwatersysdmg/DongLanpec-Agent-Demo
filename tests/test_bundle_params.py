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

    def test_tube_do_and_length_are_editable_combos(self):
        """正式程序：换热管外径 do / 公称长度 LN = 下拉可选 + 手工输入。"""
        for name, option in (("换热管外径 do", "25"), ("换热管公称长度 LN", "4500")):
            spec = params.spec_for(name, "AEU", {})
            self.assertEqual(spec.kind, "combo_edit", f"{name} 必须是可输入下拉框")
            self.assertIn(option, spec.options)
            self.assertTrue(spec.allows_manual_input)

    def test_tube_arrangement_new_wording(self):
        """正式程序 104d4358：排列方式下拉改成带角度文案，内部仍存规范名。"""
        spec = params.spec_for("换热管排列方式", "AEU", {})
        self.assertEqual(spec.kind, "combo")
        self.assertEqual(list(spec.options), list(params.TUBE_ARRANGEMENT_OPTIONS))
        self.assertEqual(params.normalize_tube_arrangement("转角正方形"), "转角正方形排列（45°）")
        self.assertEqual(params.canonical_tube_arrangement("转角正方形排列（45°）"), "转角正方形")
        self.assertEqual(params.LB_VALUE_MAP["换热管排列方式"]["转角正方形排列（45°）"], "3")
        self.assertEqual(params.LB_VALUE_MAP["换热管排列方式"]["正三角形排列（30°）"], "1")

    def test_tie_rod_diameters_follow_formal_program(self):
        self.assertNotIn("22", params.TIE_ROD_DIAMETERS)
        self.assertNotIn("24", params.TIE_ROD_DIAMETERS)
        self.assertEqual(params.spec_for("拉杆直径", "AEU", {}).options, params.TIE_ROD_DIAMETERS)

    def test_plain_text_cells_stay_text(self):
        """正式程序里折流板类型/隔条/吊环螺钉规格都是普通单元格，不是下拉框。"""
        for name in ("折流板类型", "隔条位置尺寸 W", "吊环螺钉规格"):
            spec = params.spec_for(name, "AEU", {"管程程数": {"value": "2"}})
            self.assertEqual(spec.kind, "text", f"{name} 在正式程序里是普通单元格")

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
