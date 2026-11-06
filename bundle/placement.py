"""AI 元件布置方案：AI 只给“往哪类管孔放、放几个、元件参数”，坐标由程序算。

这一层刻意不依赖 Qt，也不依赖布管页对象，方便单测与离线复用。

设计约束（沿用原始需求）：
- Agent 不能编造坐标。模型的输出里没有管孔坐标、没有方位角数值，只有选孔规则
  （region）。真正落到哪几个管孔，由 `pick_centers()` 按当次真实布管结果计算，
  同一份方案重复执行结果完全一致。
- 方案只是“草稿”：先渲染成卡片给用户过目，用户点“确认布置”才落到图形。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

# --------------------------------------------------------------------- 元件白名单
# 名称 -> 内部 kind。模型给中文名即可，也允许直接给内部名。
KIND_ALIASES = {
    "拉杆": "rod",
    "螺纹拉杆": "rod",
    "焊接拉杆": "rod",
    "rod": "rod",
    "自由拉杆": "free_rod",
    "free_rod": "free_rod",
    "中间挡管": "block_tube",
    "挡管": "block_tube",
    "block_tube": "block_tube",
    "旁路挡板": "bypass",
    "旁路挡管": "bypass",
    "bypass": "bypass",
    "中间挡板": "center_baffle",
    "中心挡板": "center_baffle",
    "center_baffle": "center_baffle",
    "滑道": "slide",
    "slide": "slide",
    "防冲板": "impingement",
    "impingement": "impingement",
    "平板形防冲板": "impingement",
    "折边式防冲板": "impingement_folded",
    "圆弧形防冲板": "impingement_folded",
    "圆弧形": "impingement_folded",
    "impingement_folded": "impingement_folded",
    "焊接式防冲板": "impingement_welded",
    "impingement_welded": "impingement_welded",
    "吊环螺钉": "screw_ring",
    "screw_ring": "screw_ring",
    "折流板": "baffle",
    "支持板": "baffle",
    "baffle": "baffle",
    "径向开孔": "radial_hole",
    "径向孔": "radial_hole",
    "radial_hole": "radial_hole",
}

# 选孔规则（位置）别名
REGION_ALIASES = {
    "外围对称": "edge_symmetric",
    "外围": "edge_symmetric",
    "对称": "edge_symmetric",
    "edge_symmetric": "edge_symmetric",
    "靠近壳壁": "near_shell",
    "靠壳壁": "near_shell",
    "近壳壁": "near_shell",
    "最外圈": "near_shell",
    "near_shell": "near_shell",
    "均布": "uniform",
    "均分": "uniform",
    "周向均布": "uniform",
    "uniform": "uniform",
    "上方": "top",
    "顶部": "top",
    "top": "top",
    "下方": "bottom",
    "底部": "bottom",
    "bottom": "bottom",
    "左侧": "left",
    "left": "left",
    "右侧": "right",
    "right": "right",
    "任意": "any",
    "随便": "any",
    "any": "any",
    "当前选中": "selected",
    "已选中": "selected",
    "selected": "selected",
}

REGION_LABEL = {
    "edge_symmetric": "靠壳壁，按分程对称展开",
    "near_shell": "取最靠壳壁的一圈管孔",
    "uniform": "沿周向均布",
    "top": "取上方的管孔",
    "bottom": "取下方的管孔",
    "left": "取左侧的管孔",
    "right": "取右侧的管孔",
    "any": "由内向外顺排",
    "selected": "使用当前已选中的管孔",
}

# 元件支持的位置规则；第一个是默认值。
# 参照管数（见 ANCHORS）决定这里的“位置”指“一个管孔”还是“一对相邻管孔”。
KIND_REGIONS = {
    "rod": ("edge_symmetric", "near_shell", "uniform", "top", "bottom", "left", "right", "any"),
    "free_rod": ("edge_symmetric", "near_shell", "uniform", "any"),
    "block_tube": ("uniform", "any", "near_shell", "top", "bottom"),
    "bypass": ("near_shell", "uniform", "top", "bottom", "left", "right", "any"),
    "center_baffle": ("uniform", "any", "top", "bottom"),
    "slide": ("top", "bottom", "left", "right", "any"),
    "impingement": ("top", "bottom", "near_shell", "uniform", "any"),
    "impingement_folded": ("top", "bottom", "near_shell", "uniform", "any"),
    "impingement_welded": ("any",),
    "screw_ring": ("uniform", "any"),
    "baffle": ("any",),
    "radial_hole": ("selected", "near_shell", "uniform", "any"),
}

# ------------------------------------------------------------------ 参照管规则
# 照抄正式程序的按钮入口，每个元件需要的“参照管孔数”：
#   拉杆      My_Piping.on_lagan_click        选 1 个种子管 → judge_linkage 对称展开
#   自由拉杆   component/free_lagan.py         同上（可不校验孔桥）
#   中间挡管   component/center_dangguan.py    选 2 个参照管 → 挡管落在 x 轴或 y 轴上
#   中间挡板   component/center_dangban.py     选 2 个参照管（必须分程隔板两侧）
#   防冲板     component/impingement_plate.py  选 2 个参照管 → 板跨两管，宽度取两管中心距
#   旁路挡板   component/side_dangban.py       每个选中管孔各生成一块（沿折流板切口方向）
#   滑道      component/slipway.py            不选管：滑道定位/形式/数量/方位角/夹角
#   吊环螺钉   component/screw_ring.py         不选管：数量 + 起始方位角 + 孔中心距
#   折流板    —                               参数驱动（轴向设计页确认）
ANCHORS = {
    "rod": 1,
    "free_rod": 1,
    "block_tube": 2,
    "center_baffle": 2,
    "impingement": 2,
    "impingement_folded": 2,
    "impingement_welded": 0,
    "bypass": 1,
    "slide": 0,
    "screw_ring": 0,
    "baffle": 0,
    "radial_hole": 1,
}

# 会替换换热管的元件（布置后该管孔不再算换热管，写库时从管孔列表移除）
OCCUPYING_KINDS = {"rod", "free_rod", "block_tube"}

# 会减少管孔计数的元件。挡板类图元画在两参照管中间/沿壳壁，不落在管孔上，
# 因此不计入占用；只有真正替换换热管的元件才算。
HOLE_OCCUPYING_KINDS = set(OCCUPYING_KINDS)

# 单次方案的数量上限，防止模型给出离谱数字
KIND_LIMITS = {
    "rod": 64,
    "free_rod": 64,
    "block_tube": 64,
    "bypass": 24,
    "center_baffle": 48,
    "slide": 12,
    "impingement": 8,
    "impingement_folded": 8,
    "impingement_welded": 8,
    "screw_ring": 64,
    "baffle": 1,
    "radial_hole": 32,
}

KIND_LABEL = {
    "rod": "拉杆",
    "free_rod": "自由拉杆",
    "block_tube": "中间挡管",
    "bypass": "旁路挡板",
    "center_baffle": "中间挡板",
    "slide": "滑道",
    "impingement": "平板形防冲板",
    "impingement_folded": "圆弧形防冲板",
    "impingement_welded": "焊接式防冲板",
    "screw_ring": "吊环螺钉",
    "baffle": "折流板",
    "radial_hole": "径向开孔",
}

# 允许模型在 options 里给的元件参数字段（都是布管页真实存在的参数名）
OPTION_FIELDS = {
    "rod": ("拉杆形式", "拉杆直径"),
    "free_rod": ("拉杆直径",),
    "block_tube": ("中间挡管安装方式",),
    "bypass": ("旁路挡板厚度", "旁路挡板宽度"),
    "center_baffle": ("中间挡板厚度", "中间挡板宽度", "中间挡板安装方式"),
    "slide": (
        "滑道定位", "滑道形式", "滑道数量", "滑道方位角", "圆钢规格",
        "滑道高度", "滑道厚度", "滑道与竖直中心线夹角", "滑道切边长度", "滑道切边高度",
    ),
    "impingement": (
        "防冲板形式", "放置位置", "防冲板厚度", "防冲板折边角度",
        "防冲板宽度", "防冲板方位角", "至圆筒内壁距离",
    ),
    "impingement_folded": ("防冲板形式", "防冲板厚度", "防冲板折边角度"),
    "impingement_welded": (
        "防冲板形式", "防冲板厚度", "防冲板折边角度", "防冲板宽度", "防冲板方位角",
        "至圆筒内壁距离",
    ),
    "screw_ring": (
        "吊环螺钉规格", "吊环螺钉数量", "吊环螺钉孔中心距", "吊环螺钉起始方位角",
    ),
    "baffle": (
        "折流/支持板外径", "折流/支持板间距", "折流板类型", "折流板切口方向",
        "折流板要求切口率", "折流板切口与中心线间距a",
    ),
    "radial_hole": (),
}


@dataclass
class PlacementItem:
    """方案里的一条布置意图。

    `anchors` 与 `overrides` 是"方案可编辑"的两个落点：
    - `anchors`：用户在方案卡上确认/改写过的参照管绝对坐标。正式程序里布置
      元件就是"先选管、再改参数"，所以一旦用户指定了管，程序不再按选孔规则
      自动挑，布置结果与卡片上写的完全一致。
    - `overrides`：用户在方案卡上改过的元件参数。AI 给的数值只是参考，只有
      用户在卡片里动手改过的参数才允许写回参数表（见 `apply_placement_plan`）。
    """

    kind: str
    count: int = 1
    region: str = "any"
    options: dict = field(default_factory=dict)
    note: str = ""
    anchors: list = field(default_factory=list)
    overrides: dict = field(default_factory=dict)

    @property
    def anchor_pairs(self) -> list:
        """两根一组切开（防冲板/中间挡板/中间挡管按对落地）。"""
        values = [tuple(a) for a in self.anchors]
        return [tuple(values[i:i + 2]) for i in range(0, len(values) - 1, 2)]

    @property
    def form(self) -> str:
        """防冲板形式（其它元件返回空串）。三种形式的几何完全不同。"""
        if self.kind not in {"impingement", "impingement_folded", "impingement_welded"}:
            return ""
        form = str(self.options.get("防冲板形式") or "").strip()
        if form:
            return form
        return {"impingement_folded": "圆弧形", "impingement_welded": "焊接式"}.get(
            self.kind, "平板形"
        )

    @property
    def label(self) -> str:
        form = self.form
        if form:
            return f"{form}防冲板"
        return KIND_LABEL.get(self.kind, self.kind)

    @property
    def occupying(self) -> bool:
        """是否会占掉一个管孔计数（供方案卡预估剩余管孔数）。"""
        return self.kind in HOLE_OCCUPYING_KINDS

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "count": self.count,
            "region": self.region,
            "options": dict(self.options),
            "note": self.note,
            "anchors": [list(a) for a in self.anchors],
            "overrides": dict(self.overrides),
        }


def normalize_kind(raw) -> str | None:
    text = str(raw or "").strip()
    if not text:
        return None
    if text in KIND_ALIASES:
        return KIND_ALIASES[text]
    # 允许“4 根螺纹拉杆”这类带修饰的写法
    for alias, kind in sorted(KIND_ALIASES.items(), key=lambda kv: len(kv[0]), reverse=True):
        if alias and alias in text:
            return kind
    return None


def normalize_region(raw, kind: str) -> str:
    text = str(raw or "").strip()
    allowed = KIND_REGIONS.get(kind, ("any",))
    if text in REGION_ALIASES:
        region = REGION_ALIASES[text]
        if region in allowed:
            return region
        return allowed[0]
    for alias, region in sorted(REGION_ALIASES.items(), key=lambda kv: len(kv[0]), reverse=True):
        if alias and alias in text and region in allowed:
            return region
    return allowed[0]


def parse_placements(raw_items, known_options: dict | None = None) -> tuple[list[PlacementItem], list[str]]:
    """把模型给的 placements 数组变成可执行方案；非法项进 rejected（人话原因）。"""
    items: list[PlacementItem] = []
    rejected: list[str] = []
    if not isinstance(raw_items, list):
        return items, rejected
    for raw in raw_items[:12]:
        if not isinstance(raw, dict):
            rejected.append("有一条布置方案格式不对，已忽略")
            continue
        kind = normalize_kind(raw.get("kind") or raw.get("component") or raw.get("name"))
        if kind is None:
            rejected.append(f"不认识的元件「{raw.get('kind') or raw.get('component') or raw.get('name')}」")
            continue
        limit = KIND_LIMITS.get(kind, 64)
        try:
            count = int(float(raw.get("count", raw.get("quantity", 1)) or 1))
        except (TypeError, ValueError):
            count = 1
        count = max(1, min(count, limit))
        region = normalize_region(raw.get("region") or raw.get("position") or raw.get("where"), kind)

        raw_options = raw.get("options") or raw.get("parameters") or {}
        options: dict = {}
        if isinstance(raw_options, dict):
            allowed = OPTION_FIELDS.get(kind, ())
            for name, value in raw_options.items():
                key = str(name).strip()
                if key in allowed and value not in (None, ""):
                    options[key] = value
        # 部分模型会把元件参数直接平铺在条目里
        for name in OPTION_FIELDS.get(kind, ()):
            if name in options:
                continue
            if isinstance(raw.get(name), (str, int, float)) and raw.get(name) not in (None, ""):
                options[name] = raw[name]

        if known_options:
            for name in list(options):
                choices = known_options.get(name)
                if choices and str(options[name]) not in [str(c) for c in choices]:
                    # 非法选项直接丢掉，回落到参数表当前值
                    options.pop(name)

        items.append(
            PlacementItem(
                kind=kind,
                count=count,
                region=region,
                options=options,
                note=str(raw.get("note") or raw.get("reason") or "")[:120],
            )
        )
    return items, rejected


# --------------------------------------------------------------------- 选孔算法
def _angle(center) -> float:
    """极角，度；0° 指向 +X，逆时针为正，范围 0–360。"""
    return math.degrees(math.atan2(center[1], center[0])) % 360.0


def _radius(center) -> float:
    return math.hypot(center[0], center[1])


SECTOR_WINDOWS = {
    "top": (45.0, 135.0),
    "bottom": (225.0, 315.0),
    "left": (135.0, 225.0),
    "right": (315.0, 405.0),   # 越过 0°，下面按取模比较
}


def _in_window(angle: float, window) -> bool:
    low, high = window
    if high <= 360.0:
        return low <= angle <= high
    return angle >= low or angle <= high - 360.0


def _angular_distance(a: float, b: float) -> float:
    diff = abs(a - b) % 360.0
    return min(diff, 360.0 - diff)


def _binned(pool, count: int, start_angle: float = 90.0):
    """按极角把管孔分成 count 瓣，每瓣取“最靠壳壁、且最贴近该瓣中线”的一个。"""
    if not pool or count <= 0:
        return []
    count = min(count, len(pool))
    span = 360.0 / count
    buckets: list[list] = [[] for _ in range(count)]
    for center in pool:
        index = int(((start_angle - _angle(center)) % 360.0) // span) % count
        buckets[index].append(center)

    def score(bucket_index: int, center) -> tuple[float, float]:
        center_angle = (start_angle - (bucket_index + 0.5) * span) % 360.0
        # 半径先按 2% 分档：同一圈管孔的坐标舍入误差不应该影响“谁更靠壳壁”
        return (int(_radius(center) / tolerance), -_angular_distance(_angle(center), center_angle))

    max_radius = max((_radius(c) for c in pool), default=1.0) or 1.0
    tolerance = max(max_radius * 0.02, 1e-9)

    picked = [
        max(bucket, key=lambda c, i=index: score(i, c))
        for index, bucket in enumerate(buckets)
        if bucket
    ]
    if len(picked) < count:
        rest = [c for c in pool if c not in picked]
        rest.sort(key=_radius, reverse=True)
        picked.extend(rest[: count - len(picked)])
    return picked[:count]


def pick_centers(pool, count: int, region: str) -> list[tuple[float, float]]:
    """按规则从真实管孔池里挑 count 个位置；找不到足量就返回实际能给的。"""
    candidates = [tuple(c) for c in pool or []]
    if not candidates or count <= 0:
        return []
    if region == "selected":
        return candidates[:count]
    window = SECTOR_WINDOWS.get(region)
    if window is not None:
        scoped = [c for c in candidates if _in_window(_angle(c), window)]
        if scoped:
            candidates = scoped
    return _binned(candidates, count)


# ------------------------------------------------------- 参照管成对选取（挡板类）
def _row_tolerance(values) -> float:
    """同一行管孔的 y 值会有 1e-3 级舍入差；用最小行距的一半做合并容差。"""
    ordered = sorted(set(round(float(v), 4) for v in values))
    gaps = [b - a for a, b in zip(ordered, ordered[1:]) if b - a > 1e-6]
    return max(min(gaps, default=1.0) * 0.4, 1e-6)


def group_lines(pool, orient: str = "row"):
    """把管孔按真实布管结果分成行（orient=row）或列（orient=col）。

    正式程序用 `group_centers_by_y` 得到 `full_sorted_current_centers_up/down`，
    防冲板/中间挡板/中间挡管都靠这两组“行”找相邻参照管。
    """
    centers = [tuple(c) for c in pool or []]
    if not centers:
        return []
    axis = 1 if orient == "row" else 0          # 行看 y，列看 x
    cross = 0 if orient == "row" else 1          # 行内按 x 排序
    tolerance = _row_tolerance(c[axis] for c in centers)
    ordered = sorted(centers, key=lambda c: (-c[axis], c[cross]))
    lines: list[list[tuple[float, float]]] = []
    current: list[tuple[float, float]] = []
    for center in ordered:
        if current and abs(center[axis] - current[-1][axis]) > tolerance:
            lines.append(sorted(current, key=lambda c: c[cross]))
            current = []
        current.append(center)
    if current:
        lines.append(sorted(current, key=lambda c: c[cross]))
    return [line for line in lines if line]


def _line_pairs(line):
    return [(a, b) for a, b in zip(line, line[1:])]


def _line_pairs_with_span(line, min_span: float):
    """同一行里“跨距刚好够 min_span”的两两组合（圆弧形折边板要跨好几根管）。"""
    pairs = []
    for index, start in enumerate(line):
        for other in line[index + 1:]:
            distance = math.hypot(other[0] - start[0], other[1] - start[1])
            if distance >= min_span - 1e-9:
                pairs.append((start, other))
                break
    return pairs


def pick_pairs(pool, count: int, region: str = "any", orient: str = "row", min_span: float = 0.0):
    """挑 count 对“同一行/列里相邻”的参照管（防冲板、中间挡板、中间挡管用）。

    正式程序里这三种元件都必须选中恰好 2 个换热管；板/挡管的几何由这两个
    参照管的真实坐标算出，模型不给方位角。

    `min_span` 用于圆弧形（折边）防冲板：折边高度 H 固定后，顶部长度
    `= 中心距 − 2H/tan(折边角)` 必须 ≥ 0，所以只接受跨距够大的那一对。

    参照 `产品设计活动表_布管元件表` 里的真实数据：类型 5/6（平板/折边防冲板）
    存的都是**同一排的两根管**（如 `[(-16,-5), (-16,-9)]`，行号相同、列号差 4），
    类型 0（拉杆）存的是对称展开后的 4 个点。所以“选管”这一步在本程序里
    就是“同一排上成对的两根换热管”，不是周向均布的单块板。
    """
    lines = group_lines(pool, orient)
    candidates = []
    axis = 1 if orient == "row" else 0
    cross = 0 if orient == "row" else 1
    for line in lines:
        if min_span > 0:
            pairs = _line_pairs_with_span(line, min_span)
        else:
            pairs = _line_pairs(line)
        if not pairs:
            continue
        # 每行优先取“跨在中心线附近”的一对，其次取“最靠壳壁”的一对
        centre_pair = min(pairs, key=lambda p: abs(p[0][cross] + p[1][cross]))
        outer_pair = max(pairs, key=lambda p: abs(p[0][cross] + p[1][cross]))
        candidates.append({
            "line": line,
            "centre": centre_pair,
            "outer": outer_pair,
            "axis_value": line[0][axis],
            "cross_value": (centre_pair[0][cross] + centre_pair[1][cross]) / 2.0,
        })
    if not candidates:
        return []
    count = max(1, min(int(count), len(candidates)))
    asc = sorted(candidates, key=lambda c: c["axis_value"])
    desc = list(reversed(asc))

    def symmetric_first(rows, reverse: bool):
        """圆弧形折边板要跨好几根管，优先挑“关于中心线对称”的那一对。"""
        if min_span <= 0:
            return rows
        return sorted(
            rows,
            key=lambda c: (
                0 if abs(c["centre"][0][cross] + c["centre"][1][cross]) <= 1.0 else 1,
                -c["axis_value"] if reverse else c["axis_value"],
            ),
        )

    if region == "top":
        return [c["centre"] for c in symmetric_first(desc, True)[:count]]
    if region == "bottom":
        return [c["centre"] for c in symmetric_first(asc, False)[:count]]
    if region in {"left", "right"}:
        by_cross = sorted(candidates, key=lambda c: c["cross_value"])
        chosen = by_cross[:count] if region == "left" else list(reversed(by_cross))[:count]
        return [c["centre"] for c in chosen]
    if region == "near_shell":
        by_edge = sorted(candidates, key=lambda c: -abs(c["cross_value"]))
        return [c["outer"] for c in by_edge[:count]]
    if region == "selected":
        return [c["centre"] for c in asc[:count]]
    # uniform / any / edge_symmetric：沿轴向等距摊开
    if count == 1:
        return [desc[len(desc) // 2]["centre"]]
    span = (len(desc) - 1) / (count - 1)
    return [desc[round(index * span)]["centre"] for index in range(count)]


def symmetric_group(centers):
    """正式程序 `judge_linkage`：原选点 + 关于 y 轴 / x 轴 / 中心对称的三个镜像。"""
    result: list[tuple[float, float]] = []
    for x, y in centers:
        for candidate in ((x, y), (-x, y), (x, -y), (-x, -y)):
            key = (round(candidate[0], 6), round(candidate[1], 6))
            if key not in {(round(c[0], 6), round(c[1], 6)) for c in result}:
                result.append((float(key[0]), float(key[1])))
    return result



# 防冲板三种形式各自生效的参数（正式程序弹窗里其余参数是灰显的）
IMPINGEMENT_FIELDS_BY_FORM = {
    "平板形": ("防冲板形式", "放置位置", "防冲板厚度"),
    "圆弧形": ("防冲板形式", "防冲板厚度", "防冲板折边角度"),
    "焊接式": (
        "防冲板形式", "防冲板厚度", "防冲板折边角度",
        "防冲板宽度", "防冲板方位角", "至圆筒内壁距离",
    ),
}


def describe_region(item: PlacementItem) -> str:
    """方案卡里的“位置（选孔规则）”，措辞对齐正式程序的选管要求。"""
    label = REGION_LABEL.get(item.region, item.region)
    anchors = ANCHORS.get(item.kind, 1)

    if item.kind == "baffle":
        return "按参数重算布管图上的折流板虚线圆"
    if item.kind == "slide":
        return "不选管：按滑道定位 / 方位角 / 夹角沿壳体内壁布置"
    if item.kind == "screw_ring":
        return "不选管：按数量 + 起始方位角沿管板外圆均布"
    if item.kind in {"rod", "free_rod"}:
        return f"选中 1 个种子管：勾“对称分布”补 4 象限镜像，不勾只按管程程数补单轴镜像（{label}）"
    if item.kind in {"impingement", "impingement_folded", "impingement_welded"}:
        form = item.form or "平板形"
        if form == "焊接式":
            return (
                "不选管：方位角（0°=顶部）+ 至圆筒内壁距离定 C 点，"
                "板宽定 PQ，A/B 落在壳体内壁圆上"
            )
        if form == "圆弧形":
            return (
                "跨 2 根参照管：折边梯形 A-P-Q-B，A/B 沿两管连线的法向向外让开 "
                f"do/2+板厚/2，中心距需 ≥ 2H/tan折边角（{label}）"
            )
        return f"跨 2 根参照管，整段沿连线法向平移 do/2+板厚/2+0.5，板长=中心距（{label}）"
    if item.kind == "center_baffle":
        return f"取分程隔板两侧相邻的 2 根参照管（{label}）"
    if item.kind == "block_tube":
        return f"取 2 根参照管，挡管落在分程隔板轴线上（{label}）"
    if item.kind == "bypass":
        return f"每个参照管各生成 1 块，沿折流板切口方向到壳壁（{label}）"
    if anchors == 2:
        return f"跨 2 根相邻参照管（{label}）"
    return label


def describe_item(item: PlacementItem, values: dict | None = None) -> dict:
    """生成卡片里的一行：元件 / 数量 / 位置 / 关键参数。"""
    values = values or {}

    def current(name):
        value = item.options.get(name)
        if value in (None, ""):
            value = values.get(name)
        return value

    names = OPTION_FIELDS.get(item.kind, ())
    if item.kind in {"impingement", "impingement_folded", "impingement_welded"}:
        # 三种形式各自只认几个参数（其余在正式程序弹窗里是灰显的）
        names = IMPINGEMENT_FIELDS_BY_FORM.get(item.form or "平板形", names)

    shown = "、".join(
        f"{name} {current(name)}"
        for name in names
        if current(name) not in (None, "")
    )
    return {
        "label": item.label,
        "count": item.count,
        "region": describe_region(item),
        "options": shown,
        "occupying": item.occupying,
    }
