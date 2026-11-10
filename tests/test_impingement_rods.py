import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication, QLabel

from bundle.page import TubeLayoutPage


class _PageHarness:
    def __init__(self):
        self.components = [
            {"kind": "rod", "center": (0.0, 0.0), "options": {"拉杆直径": "16"}},
            {"kind": "free_rod", "center": (0.0, 50.0), "options": {"自由拉杆直径": "12"}},
        ]
        self.removed = set()

    @staticmethod
    def _plot(center):
        return TubeLayoutPage._plot(center)

    def _float(self, name):
        return {
            "防冲板厚度": 4.0,
            "布管限定圆 DL": 1000.0,
            "拉杆直径": 16.0,
        }.get(name)

    def _shell_inner_radius(self):
        return 500.0

    def impingement_delete_centers(self, form, geometry, pair=None):
        return []

    def impingement_interfering_rod_centers(self, form, geometry, pair=None):
        return TubeLayoutPage.impingement_interfering_rod_centers(
            self, form, geometry, pair
        )


class ImpingementRodTests(unittest.TestCase):
    def test_reference_rod_is_preserved(self):
        page = _PageHarness()
        geometry = {
            "points": [(-10.0, 0.0), (10.0, 0.0)],
            "thickness": 4.0,
        }

        hits = TubeLayoutPage.impingement_interfering_rod_centers(
            page, "平板形", geometry, pair=[(0.0, 0.0), (20.0, 0.0)]
        )

        self.assertEqual(hits, [])

    def test_intersecting_rod_is_removed_and_remains_removed_during_edit(self):
        page = _PageHarness()
        geometry = {
            "points": [(-10.0, 0.0), (10.0, 0.0)],
            "thickness": 4.0,
        }

        deleted_count, deleted_rod_count = TubeLayoutPage._apply_impingement_deletions(
            page, geometry, "平板形"
        )

        self.assertEqual((deleted_count, deleted_rod_count), (0, 1))
        self.assertEqual(geometry["rod_deleted"], [(0.0, 0.0)])
        self.assertIn((0.0, 0.0), page.removed)
        self.assertEqual([component["kind"] for component in page.components], ["free_rod"])

        edited = {"points": [(-10.0, 20.0), (10.0, 20.0)], "thickness": 4.0}
        _deleted, edited_rod_count = TubeLayoutPage._apply_impingement_deletions(
            page,
            edited,
            "平板形",
            preserve_rod_deleted=geometry["rod_deleted"],
        )
        self.assertEqual(edited_rod_count, 0)
        self.assertEqual(edited["rod_deleted"], [(0.0, 0.0)])
        self.assertIn((0.0, 0.0), page.removed)


class DividerCorrectionTipTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_local_divider_correction_is_shown_under_rod_summary(self):
        parameters = {
            "管程分程形式": {"value": "8a"},
            "分程隔板两侧相邻管中心距（竖直）": {"value": "44"},
            "隔条位置尺寸 W": {"value": "202.390"},
            "换热管中心距 S": {"value": "32"},
            "换热管外径 do": {"value": "25"},
            "布管限定圆 DL": {"value": "900"},
            "公称直径 DN": {"value": "1000"},
            "换热管布置方式": {"value": "对中"},
            "换热管排列方式": {"value": "正三角形排列（30°）"},
            "折流板切口方向": {"value": "垂直左右"},
        }

        class _TipHarness:
            defaults = {}

            def __init__(self):
                self.parameters = parameters
                self.divider_correction_tip = QLabel()

            def _param_text(self, name):
                return str(self.parameters.get(name, {}).get("value", "") or "")

        result = SimpleNamespace(
            raw={"DL": 900.0},
            input_json={"LB_DL": "900", "LB_TubeD": "25", "LB_DN": "1000"},
        )
        page = _TipHarness()

        TubeLayoutPage._update_divider_correction_tip(page, result)

        self.assertFalse(page.divider_correction_tip.isHidden())
        text = page.divider_correction_tip.text()
        self.assertIn("修正输入Wy0值", text)
        self.assertIn("202.390", text)
        self.assertIn("188.000", text)


if __name__ == "__main__":
    unittest.main()
