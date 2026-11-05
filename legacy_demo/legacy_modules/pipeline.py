from __future__ import annotations

from dataclasses import dataclass, field

from document_reader import retrieve


KEYWORDS = (
    "管板", "布管", "管程", "分程", "中心距", "换热管", "拉杆", "旁路挡板", "防冲板",
    "折流板", "支持板", "焊", "胀", "轴向", "tube", "baffle", "tie rod", "impingement",
)


@dataclass
class PreparedDesign:
    design_id: int
    version: int
    equipment_id: str
    product_type: str
    dn: float
    base_context: dict
    evidence: list
    proposals: list[dict] = field(default_factory=list)
    conflicts: list[dict] = field(default_factory=list)
    history: list[dict] = field(default_factory=list)
    trace: list[dict] = field(default_factory=list)


class TubeBundleAgent:
    def __init__(self, repository, client=None):
        self.repository = repository
        self.client = client

    def prepare_design(self, bundle, equipment_id: str, product_type: str, dn: float) -> PreparedDesign:
        trace = [{"tool": "identify_equipment", "message": f"已确认当前设备：{equipment_id}"}]
        context = self.repository.load_base_context(product_type, dn)
        trace.append({"tool": "load_base_parameters", "message": "已装载模拟上游数据和产品型式默认值"})
        evidence = retrieve(bundle, equipment_id, KEYWORDS, 40)
        trace.append({"tool": "retrieve_evidence", "message": f"已找到 {len(evidence)} 条当前设备相关证据"})
        history = self.repository.lookup_history(product_type, dn)
        trace.append({"tool": "lookup_similar_history", "message": f"已找到 {len(history)} 个同型式/邻近直径历史方案，仅作为建议"})
        proposals, conflicts = [], []
        if self.client is not None and getattr(self.client, "configured", False):
            extracted = self.client.extract_facts(evidence, equipment_id)
            proposals = [dict(item, source="文件明确要求") for item in extracted.get("facts", [])]
            conflicts = extracted.get("conflicts", [])
            trace.append({"tool": "extract_document_facts", "message": f"DeepSeek 已提取 {len(proposals)} 条候选，{len(conflicts)} 条待确认"})
        else:
            trace.append({"tool": "extract_document_facts", "message": "未调用模型：当前使用离线审核流程，未冒充 AI 提取结果"})
        design = self.repository.create_design(equipment_id, product_type, dn, bundle.documents)
        trace.append({"tool": "prepare_review", "message": "已生成四阶段人工审核草稿；尚未写入任何阶段结果"})
        return PreparedDesign(design["id"], design["version"], equipment_id, product_type, float(dn), context, evidence, proposals, conflicts, history, trace)

