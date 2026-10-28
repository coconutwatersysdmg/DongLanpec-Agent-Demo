from __future__ import annotations

from copy import deepcopy

from models import STAGES
from rules import validate_stage


class ReviewSession:
    def __init__(self, prepared, repository):
        self.repository = repository
        self.design_id = prepared.design_id
        self.version = prepared.version
        self.parameters = deepcopy(prepared.base_context)
        self.evidence = prepared.evidence
        self.conflicts = deepcopy(prepared.conflicts)
        self.history = deepcopy(prepared.history)
        self.approved = [False] * len(STAGES)
        self.current_stage_index = 0
        self.status = "待审核"
        self.last_result = None
        if self.history:
            reference = self.history[0]
            for field, value in reference.get("components", {}).items():
                if field in self.parameters["布管与元件"]:
                    row = self.parameters["布管与元件"][field]
                    row["value"] = value
                    row["source"] = "历史建议值"
                    row["evidence"] = f"参考 {reference.get('reference')}（{reference.get('product_type')}，DN{reference.get('dn')}）"
        for proposal in prepared.proposals:
            stage = proposal.get("stage")
            field = proposal.get("parameter")
            if stage in self.parameters and field in self.parameters[stage]:
                row = self.parameters[stage][field]
                row["base_value"] = row.get("value")
                row["value"] = proposal.get("value")
                row["unit"] = proposal.get("unit") or row.get("unit", "")
                row["source"] = "文件明确要求"
                row["evidence"] = f"{proposal.get('source_ref', '')}：{proposal.get('evidence', '')}".strip("：")

    @property
    def current_stage(self):
        return STAGES[self.current_stage_index]

    @property
    def current_parameters(self):
        return self.parameters[self.current_stage]

    def apply_edit(self, field: str, value, stage: str | None = None):
        target_stage = stage or self.current_stage
        if target_stage not in self.parameters or field not in self.parameters[target_stage]:
            raise KeyError(f"未找到参数：{field}")
        index = STAGES.index(target_stage)
        if any(self.approved[index:]):
            self.version = self.repository.clear_stages_from(self.design_id, target_stage, self.version)
        for i in range(index, len(self.approved)):
            self.approved[i] = False
        self.current_stage_index = index
        row = self.parameters[target_stage][field]
        if row.get("derived"):
            raise ValueError("该参数由程序联动计算，不能直接修改")
        row["value"] = value
        row["source"] = "人工修改"
        row["evidence"] = "用户在审核表中修改"
        self.status = "待审核"
        self.last_result = None

    def run_review(self):
        result = validate_stage(self.current_stage, self.current_parameters)
        for field, value in result.derived_updates.items():
            if field in self.current_parameters:
                self.current_parameters[field]["value"] = value
                self.current_parameters[field]["source"] = "联动计算"
        self.last_result = result
        self.status = "审核通过待确认" if result.passed else "审核不通过"
        return result

    def apply_recommendation(self, issue_id: str):
        if self.last_result is None:
            raise ValueError("请先审核本阶段")
        issue = next((item for item in self.last_result.issues if item.issue_id == issue_id), None)
        if issue is None or issue.recommended is None:
            raise ValueError("该问题没有可自动采用的推荐值")
        self.apply_edit(issue.field, issue.recommended)

    def confirm_and_advance(self):
        if self.status != "审核通过待确认" or self.last_result is None or not self.last_result.passed:
            raise ValueError("请先完成审核并处理所有错误")
        stage = self.current_stage
        payload = {
            "parameters": deepcopy(self.current_parameters),
            "evidence": [
                {"source_ref": item.source_ref, "excerpt": item.excerpt[:500], "file_name": item.file_name}
                for item in self.evidence
                if not item.equipment_id or item.equipment_id
            ],
            "conflicts": deepcopy(self.conflicts),
            "review_status": "用户确认",
        }
        self.version = self.repository.save_stage(self.design_id, stage, payload, self.version)
        self.approved[self.current_stage_index] = True
        if self.current_stage_index == len(STAGES) - 1:
            self.version = self.repository.finalize_design(self.design_id, self.version)
            self.status = "已完成"
            return "已完成"
        self.current_stage_index += 1
        self.status = "待审核"
        self.last_result = None
        return self.current_stage
