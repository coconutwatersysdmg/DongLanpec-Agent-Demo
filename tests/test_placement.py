import math
import unittest

from bundle import placement


def _ring_pool():
    """构造一个同心圆管孔池，模拟真实布管结果的坐标分布。"""
    pool = []
    for ring, radius in enumerate((80, 110, 140)):
        count = (6, 8, 10)[ring]
        for index in range(count):
            angle = 2 * math.pi * index / count + ring * 0.2
            pool.append((round(radius * math.cos(angle), 2), round(radius * math.sin(angle), 2)))
    return pool


class PlacementParseTests(unittest.TestCase):
    def test_chinese_kinds_and_regions(self):
        items, rejected = placement.parse_placements([
            {"kind": "螺纹拉杆", "count": 4, "region": "靠近壳壁",
             "options": {"拉杆形式": "螺纹拉杆", "拉杆直径": 16}},
            {"kind": "旁路挡板", "count": 6, "region": "均布"},
        ])
        self.assertEqual(len(items), 2)
        self.assertEqual(rejected, [])
        rod = items[0]
        self.assertEqual((rod.kind, rod.count, rod.region), ("rod", 4, "near_shell"))
        self.assertEqual(rod.options["拉杆直径"], 16)
        self.assertTrue(rod.occupying)
        self.assertFalse(items[1].occupying)

    def test_unknown_kind_is_rejected(self):
        items, rejected = placement.parse_placements([{"kind": "外星元件", "count": 2}])
        self.assertEqual(items, [])
        self.assertTrue(rejected)

    def test_count_is_clamped_to_limit(self):
        items, _ = placement.parse_placements([{"kind": "拉杆", "count": 9999}])
        self.assertEqual(items[0].count, placement.KIND_LIMITS["rod"])

    def test_region_falls_back_to_supported_one(self):
        items, _ = placement.parse_placements([{"kind": "旁路挡板", "count": 2, "region": "上方"}])
        # 旁路挡板只能沿壳体内壁均布，非法区域回落到默认值
        self.assertIn(items[0].region, placement.KIND_REGIONS["bypass"])

    def test_flat_options_are_accepted(self):
        items, _ = placement.parse_placements([
            {"kind": "拉杆", "count": 2, "region": "均匀", "拉杆直径": "20"},
        ])
        self.assertEqual(items[0].options.get("拉杆直径"), "20")

    def test_unknown_option_is_dropped(self):
        items, _ = placement.parse_placements([
            {"kind": "拉杆", "count": 2, "options": {"不存在的参数": 1, "拉杆直径": "16"}},
        ])
        self.assertNotIn("不存在的参数", items[0].options)


class PickCenterTests(unittest.TestCase):
    def test_count_and_outer_radius(self):
        pool = _ring_pool()
        picked = placement.pick_centers(pool, 4, "near_shell")
        self.assertEqual(len(picked), 4)
        self.assertEqual(len(set(picked)), 4)
        # 全部取最外圈
        for center in picked:
            self.assertAlmostEqual(math.hypot(*center), 140.0, delta=1.0)

    def test_uniform_spreads_over_quadrants(self):
        pool = _ring_pool()
        angles = sorted(
            round(math.degrees(math.atan2(y, x)) % 360)
            for x, y in placement.pick_centers(pool, 4, "uniform")
        )
        # 四个象限各一个，相邻间隔不应挤在一起
        for previous, current in zip(angles, angles[1:]):
            self.assertGreaterEqual(current - previous, 40)
        gaps = [angles[0] + 360 - angles[-1]] + [b - a for a, b in zip(angles, angles[1:])]
        self.assertTrue(all(gap >= 40 for gap in gaps))

    def test_top_region_stays_in_upper_half(self):
        picked = placement.pick_centers(_ring_pool(), 3, "top")
        for x, y in picked:
            self.assertGreater(y, 0)

    def test_more_than_available(self):
        pool = [(10.0, 0.0), (-10.0, 0.0)]
        self.assertEqual(len(placement.pick_centers(pool, 5, "uniform")), 2)

    def test_empty_pool(self):
        self.assertEqual(placement.pick_centers([], 4, "uniform"), [])


class DescribeTests(unittest.TestCase):
    def test_describe_uses_plan_value_first(self):
        item = placement.PlacementItem("rod", 4, "near_shell", {"拉杆直径": "16"})
        row = placement.describe_item(item, {"拉杆直径": "20", "拉杆形式": "焊接拉杆"})
        self.assertIn("拉杆直径 16", row["options"])
        self.assertIn("焊接拉杆", row["options"])
        self.assertEqual(row["label"], "拉杆")
        self.assertIn("最靠壳壁", row["region"])

    def test_bypass_region_text(self):
        item = placement.PlacementItem("bypass", 4, "uniform", {})
        # 按正式程序规则：每个参照管各生成 1 块，沿折流板切口方向延伸到壳壁
        self.assertIn("每个参照管各生成 1 块", placement.describe_region(item))
        self.assertIn("折流板切口方向", placement.describe_region(item))


if __name__ == "__main__":
    unittest.main()
