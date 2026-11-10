"""防冲板几何单测：三种形式逐个对照正式程序的公式。

坐标系：与正式程序一致（Qt 场景，y 向下）——顶部是 y 更小的方向。
"""
import math
import unittest

from bundle import impingement


def _dist(a, b):
    return math.hypot(b[0] - a[0], b[1] - a[1])


class FoldedFormTests(unittest.TestCase):
    """圆弧形 = 折边梯形 A-P-Q-B（impingement_plate.build_impingement_plate）。"""

    def test_geometry_follows_formal_formulas(self):
        # 顶部一排、关于竖轴中心对称的两根参照管（场景坐标 y 向下）
        p1, p2 = (-45.26, -434.66), (45.26, -434.66)
        do, pitch, thk, angle = 25.0, 32.0, 10.0, 45.0
        geometry = impingement.folded_geometry(p1, p2, do, pitch, thk, angle)

        height = max(int(pitch) + 1, int(do / 2 + 6) + 1)
        span = _dist(p1, p2)
        top_length = span - 2 * height / math.tan(math.radians(angle))

        self.assertEqual(geometry["height"], height)
        self.assertAlmostEqual(geometry["width"], span)
        self.assertAlmostEqual(geometry["top_length"], top_length)

        points = geometry["points"]
        self.assertEqual(len(points), 4)
        A, P, Q, B = points

        # A/B 是两管圆心沿“局部 +y”（垂直于两管连线、指向圆外）平移 do/2 + 板厚/2 的点
        clearance = do / 2 + thk / 2
        unit = ((p2[0] - p1[0]) / span, (p2[1] - p1[1]) / span)
        normal = (unit[1], -unit[0])  # Qt：局部 x 轴顺时针转 90°
        mid = ((p1[0] + p2[0]) / 2.0, (p1[1] + p2[1]) / 2.0)
        if math.hypot(mid[0] + normal[0], mid[1] + normal[1]) < math.hypot(
            mid[0] - normal[0], mid[1] - normal[1]
        ):
            normal = (-normal[0], -normal[1])
        for original, moved in ((p1, A), (p2, B)):
            self.assertAlmostEqual(
                moved[0], original[0] + normal[0] * clearance, places=9
            )
            self.assertAlmostEqual(
                moved[1], original[1] + normal[1] * clearance, places=9
            )

        # P/Q 比 A/B 更远离圆心（开口朝圆心），顶部长度 = |Q - P|
        self.assertGreater(math.hypot(*P), math.hypot(*A) - 1e-9)
        self.assertAlmostEqual(_dist(P, Q), top_length)

    def test_reversing_the_pair_keeps_the_same_polygon(self):
        forward = impingement.folded_geometry((-45.0, -434.0), (45.0, -434.0), 25, 32, 10, 45)
        backward = impingement.folded_geometry((45.0, -434.0), (-45.0, -434.0), 25, 32, 10, 45)
        for a, b in zip(forward["points"], backward["points"]):
            self.assertAlmostEqual(a[0], b[0], places=9)
            self.assertAlmostEqual(a[1], b[1], places=9)

    def test_required_span_matches_formula(self):
        # 折边高 33、45° -> 跨距至少 66
        self.assertAlmostEqual(impingement.required_span_for_folded(25, 32, 45), 66.0)
        # 90° 时折边竖直，跨距没有下限
        self.assertAlmostEqual(impingement.required_span_for_folded(25, 32, 90), 0.0)

    def test_too_narrow_pair_is_rejected(self):
        # 相邻两管（跨距 45.26）配 45° 折边角 -> 顶部长度为负，正式程序弹“参数异常”
        with self.assertRaises(impingement.ImpingementError):
            impingement.folded_geometry((-22.63, -434.66), (22.63, -434.66), 25, 32, 10, 45)

    def test_angle_out_of_range_is_rejected(self):
        for angle in (10, 120):
            with self.subTest(angle=angle):
                with self.assertRaises(impingement.ImpingementError):
                    impingement.folded_geometry((-45, -434), (45, -434), 25, 32, 10, angle)


class FlatFormTests(unittest.TestCase):
    """平板形 = 一条线宽等于板厚的粗线。"""

    def test_top_line_keeps_length_and_shifts_outward(self):
        p1, p2 = (-22.63, -457.29), (22.63, -457.29)
        do, thk = 25.0, 10.0
        points = impingement.flat_points(p1, p2, do, thk, "参照管顶部连线")
        shift = do / 2 + thk / 2 + 0.5
        self.assertAlmostEqual(_dist(points[0], points[1]), _dist(p1, p2))
        # 上半圆外侧 = 场景 y 更小
        self.assertAlmostEqual(points[0][1], p1[1] - shift)
        self.assertAlmostEqual(points[1][1], p2[1] - shift)
        self.assertAlmostEqual(points[0][0], p1[0])

    def test_lower_half_shifts_below_reference_tubes(self):
        p1, p2 = (-22.63, 457.29), (22.63, 457.29)
        do, thk = 25.0, 10.0
        points = impingement.flat_points(p1, p2, do, thk, "参照管顶部连线")
        shift = do / 2 + thk / 2 + 0.5
        self.assertAlmostEqual(_dist(points[0], points[1]), _dist(p1, p2))
        self.assertAlmostEqual(points[0][1], p1[1] + shift)
        self.assertAlmostEqual(points[1][1], p2[1] + shift)

    def test_outward_side_is_selected_for_a_sloped_lower_pair(self):
        pair = [(-30.0, 400.0), (30.0, 430.0)]
        points = impingement.flat_points(pair[0], pair[1], 25.0, 10.0)
        midpoint = ((pair[0][0] + pair[1][0]) / 2, (pair[0][1] + pair[1][1]) / 2)

        self.assertGreater(
            (points[0][0] + points[1][0]) / 2 * midpoint[0]
            + (points[0][1] + points[1][1]) / 2 * midpoint[1],
            midpoint[0] ** 2 + midpoint[1] ** 2,
        )

    def test_center_line_shrinks_by_do(self):
        p1, p2 = (-22.63, -457.29), (22.63, -457.29)
        do = 25.0
        points = impingement.flat_points(p1, p2, do, 10.0, "参照管中心连线")
        self.assertAlmostEqual(_dist(points[0], points[1]), _dist(p1, p2) - do)
        # 两端各内缩 do/2，仍在同一条直线上
        self.assertAlmostEqual(points[0][1], p1[1])
        self.assertAlmostEqual(points[0][0], p1[0] + do / 2)

    def test_too_short_span_on_center_line_is_rejected(self):
        with self.assertRaises(impingement.ImpingementError):
            impingement.flat_points((0.0, 0.0), (25.0, 0.0), 25.0, 10.0, "参照管中心连线")


class WeldedFormTests(unittest.TestCase):
    """焊接式：方位角 + 至圆筒内壁距离定 C，板宽定 PQ，A/B 落在壳体内壁圆上。"""

    def test_azimuth_zero_is_the_top(self):
        shell_radius, distance, width = 500.0, 150.0, 200.0
        geometry = impingement.welded_geometry(25, 10, width, 0, distance, shell_radius, 45)
        A, P, Q, B = geometry["points"]
        self.assertAlmostEqual(P[1], -(shell_radius - distance))
        self.assertAlmostEqual(Q[1], -(shell_radius - distance))
        self.assertAlmostEqual(_dist(P, Q), width)
        self.assertAlmostEqual(P[0], -width / 2)
        for point in (A, B):
            self.assertAlmostEqual(math.hypot(*point), shell_radius, places=6)

    def test_azimuth_ninety_moves_to_the_right(self):
        geometry = impingement.welded_geometry(25, 10, 200, 90, 150, 500, 45)
        _A, P, Q, _B = geometry["points"]
        # 方位角 90° = 屏幕右侧
        self.assertAlmostEqual((P[0] + Q[0]) / 2, 350.0, places=6)
        self.assertAlmostEqual((P[1] + Q[1]) / 2, 0.0, places=6)

    def test_distance_beyond_the_shell_is_rejected(self):
        with self.assertRaises(impingement.ImpingementError):
            impingement.welded_geometry(25, 10, 200, 0, 600, 500, 45)

    def test_missing_width_is_rejected(self):
        with self.assertRaises(impingement.ImpingementError):
            impingement.welded_geometry(25, 10, 0, 0, 150, 500, 45)


class FormDispatchTests(unittest.TestCase):
    def test_kind_follows_form(self):
        pair = [(-45.0, -434.0), (45.0, -434.0)]
        flat = impingement.geometry_for_form(
            "平板形", pair, tube_outer_diameter=25, tube_pitch=32, thickness=10,
            fold_angle=45, placement="参照管顶部连线",
        )
        self.assertEqual(flat["kind"], "impingement")
        self.assertEqual(len(flat["points"]), 2)

        folded = impingement.geometry_for_form(
            "圆弧形", pair, tube_outer_diameter=25, tube_pitch=32, thickness=10, fold_angle=45
        )
        self.assertEqual(folded["kind"], "impingement_folded")
        self.assertEqual(len(folded["points"]), 4)

        welded = impingement.geometry_for_form(
            "焊接式", None, tube_outer_diameter=25, tube_pitch=32, thickness=10,
            fold_angle=45, width=200, azimuth=0, distance_to_shell=150,
            shell_inner_radius=500,
        )
        self.assertEqual(welded["kind"], "impingement_welded")

    def test_folded_needs_a_pair(self):
        with self.assertRaises(impingement.ImpingementError):
            impingement.geometry_for_form(
                "圆弧形", None, tube_outer_diameter=25, tube_pitch=32,
                thickness=10, fold_angle=45,
            )

    def test_unknown_form_is_rejected(self):
        with self.assertRaises(impingement.ImpingementError):
            impingement.geometry_for_form(
                "波浪形", None, tube_outer_diameter=25, tube_pitch=32,
                thickness=10, fold_angle=45,
            )


class InterferenceTests(unittest.TestCase):
    """删管规则：`calculate_and_update_interfering_tubes` / `collect_extra_...` / `welded`。"""

    def test_tube_touching_the_plate_band_is_hit(self):
        # 平板沿 y=0 铺开、板厚 10、管外径 25 → 管心离中线 ≤ 5+12.5 就算压到
        points = [(-100.0, 0.0), (100.0, 0.0)]
        centers = [(0.0, 0.0), (0.0, 17.0), (0.0, 18.0), (0.0, 200.0)]
        hits = impingement.interference_centers(points, 10.0, 25.0, centers)
        self.assertIn((0.0, 0.0), hits)
        self.assertIn((0.0, 17.0), hits)     # 12.5 + 5 = 17.5，刚好压住
        self.assertNotIn((0.0, 18.0), hits)
        self.assertNotIn((0.0, 200.0), hits)

    def test_folded_checks_every_segment(self):
        # A-P-Q-B：中间水平段压住 (0, -40)，两条斜边各压住一根
        points = [(-100.0, 0.0), (-60.0, -40.0), (60.0, -40.0), (100.0, 0.0)]
        centers = [(0.0, -40.0), (-80.0, -25.0), (80.0, -25.0), (0.0, 80.0)]
        hits = impingement.interference_centers(points, 10.0, 25.0, centers)
        self.assertIn((0.0, -40.0), hits)
        self.assertIn((-80.0, -25.0), hits)
        self.assertIn((80.0, -25.0), hits)
        self.assertNotIn((0.0, 80.0), hits)

    def test_outer_cap_beyond_the_chord_is_deleted(self):
        # 弦在 y=80，壳体中心在原点 → y>80 的那片弓形区全删，弦上的两端点管保留
        pair = [(-20.0, 80.0), (20.0, 80.0)]
        centers = [
            (-20.0, 80.0), (20.0, 80.0),   # 两块参照管
            (-40.0, 80.0), (40.0, 80.0),   # 弦延长线上的管：不删
            (0.0, 100.0), (-40.0, 100.0),  # 弦外侧：删
            (0.0, 60.0),                   # 弦内侧：不删
            (0.0, 400.0),                  # 布管限定圆外：不删
        ]
        extra = impingement.outer_cap_centers(pair, centers, limit_radius=300.0)
        self.assertEqual(
            sorted(extra), sorted([(0.0, 100.0), (-40.0, 100.0)])
        )

    def test_welded_fan_region_and_segment_distance(self):
        # 顶部焊接式：板宽 200、至内壁 60、壳体内半径 500
        geometry = impingement.welded_geometry(25, 10, 200, 0, 60, 500, 45)
        points = geometry["points"]
        centers = [
            (0.0, -470.0),    # 板与壳顶之间（扇形内）
            (0.0, -442.0),    # 在 P-Q 外侧、离板 2mm（线段距离 ≤ 12.5+5）
            (0.0, -420.0),    # 板背后（朝圆心一侧）：不删
            (0.0, -200.0),    # 远离防冲板：不删
            (240.0, -450.0),  # 侧后方：不在板宽范围
            (0.0, -520.0),    # 壳体大圆外
        ]
        hits = impingement.welded_interference_centers(
            points, 10.0, 25.0, centers, shell_radius=500.0
        )
        self.assertIn((0.0, -470.0), hits)
        self.assertIn((0.0, -442.0), hits)
        self.assertNotIn((0.0, -420.0), hits)
        self.assertNotIn((0.0, -200.0), hits)
        self.assertNotIn((240.0, -450.0), hits)
        self.assertNotIn((0.0, -520.0), hits)


if __name__ == "__main__":
    unittest.main()
