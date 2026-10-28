from __future__ import annotations

import math

from models import ValidationIssue, ValidationResult


def _raw(parameters, field, default=None):
    item = parameters.get(field, {})
    return item.get("value", default) if isinstance(item, dict) else item


def _number(parameters, field, issues, recommended=None):
    raw = _raw(parameters, field)
    try:
        value = float(raw)
        if not math.isfinite(value):
            raise ValueError
        return value
    except (TypeError, ValueError):
        issues.append(ValidationIssue(f"number:{field}", field, "请输入有效数字", recommended))
        return None


def _positive(parameters, field, issues, recommended):
    value = _number(parameters, field, issues, recommended)
    if value is not None and value <= 0:
        issues.append(ValidationIssue(f"positive:{field}", field, "必须大于 0", recommended))
    return value


def validate_stage(stage: str, parameters: dict, components=None) -> ValidationResult:
    issues: list[ValidationIssue] = []
    updates = {}
    warnings = ["Demo 已执行共用参数规则；当前产品型式的全部专用工程规则尚未覆盖，请人工确认。"]
    if stage == "管板型式":
        dn = _positive(parameters, "公称直径 DN", issues, 700.0)
        r2 = _number(parameters, "R2", issues, 12.0)
        if r2 is not None and r2 < 0:
            issues.append(ValidationIssue("range:R2", "R2", "圆角半径不能小于 0", 12.0))
        if dn is not None and r2 is not None:
            dl = round(dn - 2 * r2, 3)
            if dl <= 0:
                issues.append(ValidationIssue("range:DL", "R2", "R2 过大，导致布管限定圆不大于 0", 12.0))
            else:
                updates["布管限定圆 DL"] = dl
        for field, recommended in (("R1", 12.0), ("h", 1.5), ("ρ", 3.0), ("e", 0.5)):
            value = _number(parameters, field, issues, recommended)
            if value is not None and value < 0:
                issues.append(ValidationIssue(f"range:{field}", field, "不能小于 0", recommended))
        alpha = _number(parameters, "α", issues, 2.0)
        if alpha is not None and not 0 <= alpha <= 180:
            issues.append(ValidationIssue("range:alpha", "α", "角度必须在 0° 到 180° 之间", 2.0))

    elif stage == "布管与元件":
        diameter = _positive(parameters, "换热管外径 do", issues, 25.0)
        wall = _positive(parameters, "换热管壁厚 δ", issues, 2.0)
        pitch = _positive(parameters, "换热管中心距 S", issues, 32.0)
        if diameter is not None and wall is not None and wall * 2 >= diameter:
            issues.append(ValidationIssue("wall:too_thick", "换热管壁厚 δ", "壁厚的 2 倍必须小于换热管外径", round(diameter * 0.08, 2)))
        if diameter is not None and pitch is not None and pitch <= diameter:
            issues.append(ValidationIssue("pitch:too_small", "换热管中心距 S", "换热管中心距必须大于换热管外径", round(diameter + 7.0, 2)))
        passes = _number(parameters, "管程程数", issues, 2)
        passes_integer = passes is not None and passes.is_integer()
        if passes is not None and (not passes_integer or int(passes) not in {1, 2, 4, 6, 8, 10, 12}):
            issues.append(ValidationIssue("passes:unsupported", "管程程数", "管程程数必须为整数 1、2、4、6、8、10 或 12", 2))
        if passes_integer:
            form = str(_raw(parameters, "管程分程形式", ""))
            if not form.startswith(str(int(passes)) + "程"):
                issues.append(ValidationIssue("passes:form", "管程分程形式", "分程形式必须与管程程数一致", f"{int(passes)}程-水平分程"))
        for field in ("分程隔板两侧相邻管中心距（竖直）", "分程隔板两侧相邻管中心距（水平）"):
            gap = _positive(parameters, field, issues, 100.0)
            if gap is not None and pitch is not None and gap < pitch:
                issues.append(ValidationIssue(f"gap:{field}", field, "分程隔板相邻管中心距不能小于换热管中心距", round(pitch, 2)))
        for quantity_field in ("拉杆数量", "旁路挡板数量", "防冲板数量"):
            quantity = _number(parameters, quantity_field, issues, 0)
            if quantity is not None and (quantity < 0 or not quantity.is_integer()):
                issues.append(ValidationIssue(f"quantity:{quantity_field}", quantity_field, "数量必须为非负整数", max(0, int(quantity))))
        component_rules = (
            ("拉杆数量", ("拉杆直径",)),
            ("旁路挡板数量", ("旁路挡板厚度", "旁路挡板宽度")),
            ("防冲板数量", ("防冲板厚度", "防冲板宽度")),
        )
        for quantity_field, dimension_fields in component_rules:
            quantity = _number(parameters, quantity_field, issues, 0)
            if quantity is not None and quantity > 0:
                for field in dimension_fields:
                    _positive(parameters, field, issues, 1.0)

    elif stage == "管-板连接":
        thickness = _positive(parameters, "管板厚度 δt", issues, 60.0)
        lf = _number(parameters, "贴胀长度 lf", issues, 3.0)
        groove = _number(parameters, "坡口长度 lgroove", issues, 2.0)
        inner = _number(parameters, "内伸长度 linner", issues, 0.0)
        if lf is not None and lf < 0:
            issues.append(ValidationIssue("weld:lf_negative", "贴胀长度 lf", "贴胀长度不能小于 0", 3.0))
        if thickness is not None and lf is not None and lf >= thickness:
            issues.append(ValidationIssue("weld:lf_thickness", "贴胀长度 lf", "贴胀长度必须小于管板厚度", 3.0))
        if groove is not None and groove < 0:
            issues.append(ValidationIssue("weld:groove_negative", "坡口长度 lgroove", "坡口长度不能小于 0", 2.0))
        if inner is not None and inner < 0:
            issues.append(ValidationIssue("weld:inner_negative", "内伸长度 linner", "内伸长度不能小于 0", 0.0))
        form = str(_raw(parameters, "焊接结构形式", "c")).lower()
        if lf is not None and groove is not None and inner is not None:
            if form == "a":
                length = lf
            elif form == "b":
                length = groove
            elif form in {"c", "d"}:
                length = lf + groove
            elif form == "e":
                length = lf + inner
            else:
                issues.append(ValidationIssue("weld:form", "焊接结构形式", "焊接结构形式应为 a、b、c、d 或 e", "c"))
                length = None
            if length is not None:
                if length < 0:
                    issues.append(ValidationIssue("weld:length_negative", "焊接计算长度 L", "联动得到的焊接计算长度不能小于 0", 0.0))
                else:
                    updates["焊接计算长度 L"] = round(length, 3)

    elif stage == "轴向设计":
        length = _positive(parameters, "换热管公称长度 LN", issues, 4500.0)
        protrusion = _number(parameters, "伸出管板长度 L_ext", issues, 3.0)
        if protrusion is not None and length is not None and not (0 <= protrusion <= length):
            issues.append(ValidationIssue("axial:protrusion", "伸出管板长度 L_ext", "伸出管板长度必须在 0 到换热管公称长度之间", 3.0))
        for field in ("第一块折流板距管板", "折流板间距", "末块折流板距管板", "折流板厚度"):
            _positive(parameters, field, issues, 10.0 if field == "折流板厚度" else 300.0)
    else:
        issues.append(ValidationIssue("stage:unknown", "", "未知审核阶段", None))
    return ValidationResult(not issues, issues, updates, warnings)

