"""四阶段管束设计会话：保留顺序、下游失效、最终一次事务写库。

状态机与正式程序 Tab 一致：管板型式 → 布管 → 管-板连接 → 轴向设计。
- 每个 Tab 只有通过校验才能“保留”，保留后自动进入下一个 Tab。
- 修改已经保留的 Tab，会把它之后的草稿全部作废（approved 置 False 并清空 payload），
  避免前后参数矛盾。
- 四个 Tab 全部保留后，才允许调用正式保存逻辑（ProductionRepository.save_design），
  且写库在单个事务内完成，失败回滚。
"""
from __future__ import annotations

from copy import deepcopy

from PyQt5.QtCore import QObject, pyqtSignal

from bundle.engine import check_geometry
from db.production import DatabaseUnavailable, SaveFailed
from models import STAGES


class DesignSession(QObject):
    stage_changed = pyqtSignal(int)
    saved = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, repository, product: dict, upstream: dict, parent=None):
        super().__init__(parent)
        self.repository = repository
        self.product = dict(product or {})
        self.product_id = str(self.product.get("产品ID", ""))
        self.project_id = str(self.product.get("项目ID", ""))
        self.product_type = str(self.product.get("产品型式", "AEU") or "AEU").strip().upper()
        self.upstream = dict(upstream or {})
        self.approved = [False] * len(STAGES)
        self.payloads: dict[str, dict] = {}
        self.current_index = 0
        self.saved_result: dict | None = None
        self.dirty_reason = ""

    # ------------------------------------------------------------------ 基础
    @property
    def current_stage(self) -> str:
        return STAGES[self.current_index]

    @property
    def complete(self) -> bool:
        return all(self.approved)

    @property
    def next_unapproved(self) -> int | None:
        for index, flag in enumerate(self.approved):
            if not flag:
                return index
        return None

    def dn(self) -> float:
        for key in ("公称直径", "公称直径 DN", "DN"):
            row = self.upstream.get(key)
            if isinstance(row, dict) and row.get("value"):
                try:
                    return float(str(row["value"]).strip())
                except (TypeError, ValueError):
                    continue
        return 1000.0

    def header_text(self) -> str:
        return f"{self.product_id} · {self.product_type} · DN{self.dn():g}"

    # ------------------------------------------------------------------ 保留
    def mark_kept(self, stage: str, payload: dict) -> None:
        if stage not in STAGES:
            raise ValueError(f"未知阶段：{stage}")
        index = STAGES.index(stage)
        self.payloads[stage] = deepcopy(payload)
        self.approved[index] = True
        # 下游作废：保留上游后，后续 Tab 的草稿必须重算
        for later in range(index + 1, len(STAGES)):
            if self.approved[later]:
                self.dirty_reason = f"{stage} 已修改，{STAGES[later]} 需要重新计算"
            self.approved[later] = False
            self.payloads.pop(STAGES[later], None)
        self.saved_result = None
        self.saved_payload = None
        if index < len(STAGES) - 1:
            self.current_index = index + 1
        self.stage_changed.emit(self.current_index)

    def invalidate_from(self, stage: str) -> None:
        index = STAGES.index(stage)
        for later in range(index, len(STAGES)):
            self.approved[later] = False
            self.payloads.pop(STAGES[later], None)
        self.saved_result = None
        self.current_index = index
        self.stage_changed.emit(self.current_index)

    def can_keep(self, stage: str) -> tuple[bool, str]:
        index = STAGES.index(stage)
        for earlier in range(index):
            if not self.approved[earlier]:
                return False, f"请先完成并保留“{STAGES[earlier]}”"
        return True, ""

    # ------------------------------------------------------------------ 保存
    def build_payload(self) -> dict:
        missing = [stage for stage in STAGES if stage not in self.payloads]
        if missing:
            raise SaveFailed("以下 Tab 尚未保留：" + "、".join(missing))
        layout = deepcopy(self.payloads["布管"])
        sheet = deepcopy(self.payloads["管板型式"])
        connection = deepcopy(self.payloads["管-板连接"])
        axial = deepcopy(self.payloads["轴向设计"])
        return {
            "product_id": self.product_id,
            "project_id": self.project_id,
            "product_type": self.product_type,
            "sheet_form": {
                "parameters": {k: v for k, v in sheet.get("parameters", {}).items()
                               if k not in {"产品型式", "公称直径 DN", "管板类型", "布管限定圆 DL"}},
                "管板类型": sheet.get("管板类型", "a"),
                "image": sheet.get("image", ""),
            },
            "layout": layout,
            "tube_connection": connection,
            "axial": axial,
        }

    def preview_statements(self) -> list[str]:
        try:
            return self.repository.explain_save(self.build_payload())
        except Exception as exc:  # noqa: BLE001
            return [f"无法生成写库计划：{exc}"]

    def save(self, confirm: bool = True) -> dict:
        """四个 Tab 全部保留后的最终写库（单事务，失败回滚）。"""
        if not self.complete:
            raise SaveFailed("四个 Tab 尚未全部保留，不能写库")
        payload = self.build_payload()
        if not confirm:
            return self.repository.save_design(payload, dry_run=True)
        self.repository.allow_write = True
        try:
            result = self.repository.save_design(payload, dry_run=False)
        except (SaveFailed, DatabaseUnavailable) as exc:
            self.failed.emit(str(exc))
            raise
        self.saved_result = result
        self.saved_payload = payload
        self.saved.emit(result)
        return result

    # ------------------------------------------------------------------ 布管联动
    def layout_linkage(self, sheet_payload: dict) -> dict:
        """管板型式 → 布管：布管限定圆 DL 由 DN 与 R2 决定（正式程序同名联动）。"""
        dn = self.dn()
        try:
            r2 = float(str(sheet_payload.get("R2", 8.0)))
        except (TypeError, ValueError):
            r2 = 8.0
        return {"布管限定圆 DL": f"{max(dn - 2 * r2, 0):g}"}

    def axial_linkage(self, layout_payload: dict, connection_payload: dict) -> dict:
        parameters = layout_payload.get("parameters", {})
        length = parameters.get("换热管公称长度 LN", {}).get("value", "")
        spacing = parameters.get("折流/支持板间距", {}).get("value", "")
        thickness = connection_payload.get("parameters", {}).get("管板厚度 δt", "")
        result = {}
        if length:
            result["换热管公称长度 LN"] = length
        if spacing:
            result["折流板间距"] = spacing
        if thickness:
            result["管板厚度 δt"] = thickness
        return result

    def layout_geometry_issues(self, parameters: dict, result=None) -> list[dict]:
        return check_geometry(parameters, result)
