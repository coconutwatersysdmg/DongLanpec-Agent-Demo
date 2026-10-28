import unittest

from demo_db import DemoRepository
from rules import validate_stage


class RulesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = DemoRepository(":memory:")

    @classmethod
    def tearDownClass(cls):
        cls.repo.close()

    def stage(self, name):
        return self.repo.load_base_context("AEU", 700)[name]

    def test_tube_sheet_recomputes_dl(self):
        params = self.stage("管板型式")
        params["R2"]["value"] = 12
        result = validate_stage("管板型式", params)
        self.assertTrue(result.passed)
        self.assertEqual(result.derived_updates["布管限定圆 DL"], 676)

    def test_bad_wall_and_pitch_have_field_recommendations(self):
        params = self.stage("布管与元件")
        params["换热管壁厚 δ"]["value"] = 13
        params["换热管中心距 S"]["value"] = 20
        result = validate_stage("布管与元件", params)
        by_field = {issue.field: issue for issue in result.issues}
        self.assertFalse(result.passed)
        self.assertIn("换热管壁厚 δ", by_field)
        self.assertEqual(by_field["换热管壁厚 δ"].recommended, 2.0)
        self.assertEqual(by_field["换热管中心距 S"].recommended, 32.0)

    def test_weld_length_constraint_and_derived_length(self):
        params = self.stage("管-板连接")
        params["贴胀长度 lf"]["value"] = 60
        result = validate_stage("管-板连接", params)
        self.assertFalse(result.passed)
        issue = next(i for i in result.issues if i.field == "贴胀长度 lf")
        self.assertIn("小于管板厚度", issue.message)
        self.assertEqual(issue.recommended, 3.0)
        params["贴胀长度 lf"]["value"] = 3
        result = validate_stage("管-板连接", params)
        self.assertEqual(result.derived_updates["焊接计算长度 L"], 5)

    def test_axial_protrusion_must_be_inside_tube_length(self):
        params = self.stage("轴向设计")
        params["伸出管板长度 L_ext"]["value"] = 5000
        result = validate_stage("轴向设计", params)
        issue = next(i for i in result.issues if i.field == "伸出管板长度 L_ext")
        self.assertEqual(issue.recommended, 3.0)


if __name__ == "__main__":
    unittest.main()
