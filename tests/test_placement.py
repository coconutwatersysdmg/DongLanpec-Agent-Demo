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


class HoleOpTests(unittest.TestCase):
    """换热管增删方案：模型只给区域，坐标由界面算（这里只校验解析这一层）。"""

    def test_parse_delete_with_groove_rows(self):
        ops, rejected = placement.parse_hole_ops([
            {"op": "delete", "region": "隔板槽两侧", "rows": 2, "count": 0},
        ])
        self.assertEqual(rejected, [])
        self.assertEqual(len(ops), 1)
        self.assertEqual((ops[0].op, ops[0].region, ops[0].rows), ("delete", "groove", 2))
        self.assertIn("隔板槽两侧最近 2 排", ops[0].describe())
        self.assertEqual(ops[0].label, "删除换热管")

    def test_parse_restore_and_region_fallback(self):
        ops, _ = placement.parse_hole_ops([{"op": "恢复", "region": "最靠壳壁"}])
        self.assertEqual(ops[0].op, "restore")
        self.assertEqual(ops[0].region, "near_shell")
        ops, _ = placement.parse_hole_ops([{"op": "delete", "region": "看不懂的位置"}])
        self.assertEqual(ops[0].region, "groove")

    def test_bad_items_are_rejected(self):
        ops, rejected = placement.parse_hole_ops(["不是字典"])
        self.assertEqual(ops, [])
        self.assertTrue(rejected)


class UIActionTests(unittest.TestCase):
    """界面动作：用户能点的按钮，模型也能给同名动作（解析层单测）。"""

    def test_parse_by_name_and_chinese_alias(self):
        actions, rejected = placement.parse_ui_actions([
            {"name": "clear_selection"},
            {"action": "取消全选"},
            {"name": "select_region", "region": "最外圈", "rows": 1},
        ])
        self.assertEqual(rejected, [])
        self.assertEqual([a.name for a in actions],
                         ["clear_selection", "clear_selection", "select_region"])
        # “最外圈”= 布管外轮廓（每行两端 + 最上/最下一整排），不再是按半径剥离的一圈
        self.assertEqual(actions[2].region, "outline")
        self.assertIn("每行最左、最右", actions[2].describe())
        self.assertIn("最上、最下一整排", actions[2].describe())

    def test_stage_and_kind_fields(self):
        actions, _ = placement.parse_ui_actions([
            {"name": "switch_stage", "stage": "布管"},
            {"name": "delete_components", "kind": "旁路挡板"},
        ])
        self.assertEqual(actions[0].stage, "布管")
        self.assertEqual(actions[1].kind, "bypass")

    def test_unknown_action_rejected_in_plain_words(self):
        actions, rejected = placement.parse_ui_actions([{"name": "把图纸撕了"}])
        self.assertEqual(actions, [])
        self.assertTrue(rejected)

    def test_brief_covers_core_buttons(self):
        brief = placement.ui_action_brief()
        for name in ("clear_selection", "select_all", "dump_holes", "undo",
                     "switch_stage", "keep_stage"):
            self.assertIn(name, brief)


class HoleRegionTests(unittest.TestCase):
    def test_removed_region_alias(self):
        ops, _ = placement.parse_hole_ops([{"op": "restore", "region": "已删除"}])
        self.assertEqual(ops[0].region, "removed")
        self.assertIn("removed", placement.HOLE_REGIONS)


class ComponentActionTests(unittest.TestCase):
    """元件类操作：要拉杆就给拉杆的数据，不是换热管；删元件要把孔还回去。"""

    def test_parse_element_actions(self):
        actions, rejected = placement.parse_ui_actions([
            {"name": "dump_components", "kind": "拉杆"},
            {"name": "convert_to_tube", "kind": "自由拉杆"},
            {"name": "remove_components", "kind": "旁路挡板"},
        ])
        self.assertEqual(rejected, [])
        self.assertEqual([a.name for a in actions],
                         ["dump_components", "convert_to_tube", "remove_components"])
        self.assertEqual([a.kind for a in actions], ["rod", "free_rod", "bypass"])

    def test_brief_lists_element_actions(self):
        brief = placement.ui_action_brief()
        for name in ("dump_components", "remove_components", "convert_to_tube"):
            self.assertIn(name, brief)


if __name__ == "__main__":
    unittest.main()
