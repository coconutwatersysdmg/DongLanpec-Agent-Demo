from __future__ import annotations

import json
import os
import sqlite3
from copy import deepcopy
from pathlib import Path
from typing import Any

from models import ParameterValue, STAGES


DEFAULT_DB_PATH = Path(
    os.environ.get("TUBE_AGENT_DEMO_DB")
    or (Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "DongLanpecAgentDemo" / "tube_agent_demo.sqlite3")
)


class VersionConflict(RuntimeError):
    pass


def _p(value, unit="", source="程序默认值", evidence="", editable=True, derived=False):
    return ParameterValue(value, unit, source, evidence, editable, derived).to_dict()


def _seed_context(product_type: str, dn: float) -> dict[str, dict[str, dict]]:
    product_type = (product_type or "AEU").upper()
    dn = float(dn or 700)
    u_type = product_type in {"AEU", "BEU", "AKU", "BKU"}
    floating = product_type in {"AES", "BES"}
    plate_type = "a（U形管）" if u_type else ("a（浮头式）" if floating else "b（固定管板）")
    connection = "强度焊＋贴胀" if u_type or floating else "强度焊"
    return {
        "管板型式": {
            "产品型式": _p(product_type, source="模拟上游数据", evidence="模拟总Agent传入", editable=False),
            "公称直径 DN": _p(dn, "mm", "模拟上游数据", "模拟前面模块设计数据", editable=False),
            "管板类型": _p(plate_type),
            "R1": _p(12.0, "mm"),
            "R2": _p(12.0, "mm"),
            "h": _p(1.5, "mm"),
            "α": _p(2.0, "°"),
            "ρ": _p(3.0, "mm"),
            "e": _p(0.5, "mm"),
            "布管限定圆 DL": _p(dn - 24.0, "mm", "联动计算", "DL = DN - 2×R2", editable=False, derived=True),
        },
        "布管与元件": {
            "管程程数": _p(2),
            "管程分程形式": _p("2程-水平分程"),
            "壳程程数": _p(1),
            "换热管布置方式": _p("转角正方形"),
            "换热管外径 do": _p(25.0, "mm"),
            "换热管壁厚 δ": _p(2.0, "mm"),
            "换热管中心距 S": _p(32.0, "mm"),
            "换热管公称长度 LN": _p(4500.0, "mm", "模拟上游数据", "模拟元件附加参数"),
            "分程隔板两侧相邻管中心距（竖直）": _p(100.0, "mm"),
            "分程隔板两侧相邻管中心距（水平）": _p(100.0, "mm"),
            "拉杆直径": _p(16.0, "mm"),
            "拉杆数量": _p(8),
            "旁路挡板数量": _p(2),
            "旁路挡板厚度": _p(6.0, "mm"),
            "旁路挡板宽度": _p(40.0, "mm"),
            "防冲板数量": _p(1),
            "防冲板厚度": _p(6.0, "mm"),
            "防冲板宽度": _p(300.0, "mm"),
            "U形管根数": _p("", "根"),
            "管孔数": _p("", "个"),
        },
        "管-板连接": {
            "管板连接方式": _p(connection),
            "焊接结构形式": _p("c"),
            "管板厚度 δt": _p(60.0, "mm"),
            "贴胀长度 lf": _p(3.0, "mm"),
            "坡口长度 lgroove": _p(2.0, "mm"),
            "内伸长度 linner": _p(0.0, "mm"),
            "焊接计算长度 L": _p(5.0, "mm", "联动计算", "形式c：L=lf+lgroove", editable=False, derived=True),
        },
        "轴向设计": {
            "换热管公称长度 LN": _p(4500.0, "mm", "联动计算", "来自布管阶段", editable=False, derived=True),
            "伸出管板长度 L_ext": _p(3.0, "mm"),
            "第一块折流板距管板": _p(300.0, "mm"),
            "折流板间距": _p(450.0, "mm"),
            "末块折流板距管板": _p(300.0, "mm"),
            "折流板厚度": _p(12.0, "mm"),
        },
    }


HISTORY = [
    {"reference": "H-AEU-0700-01", "product_type": "AEU", "dn": 700, "components": {"拉杆数量": 8, "拉杆直径": 16, "旁路挡板数量": 2, "防冲板数量": 1}},
    {"reference": "H-AEU-1300-01", "product_type": "AEU", "dn": 1300, "components": {"拉杆数量": 8, "拉杆直径": 16, "旁路挡板数量": 2, "防冲板数量": 1}},
    {"reference": "H-BES-0700-01", "product_type": "BES", "dn": 700, "components": {"拉杆数量": 6, "拉杆直径": 16, "旁路挡板数量": 2, "防冲板数量": 1}},
    {"reference": "H-BKU-0900-01", "product_type": "BKU", "dn": 900, "components": {"拉杆数量": 8, "拉杆直径": 20, "旁路挡板数量": 2, "防冲板数量": 1}},
]


class DemoRepository:
    def __init__(self, path: str | Path = DEFAULT_DB_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(str(self.path))
        self.connection.row_factory = sqlite3.Row
        self._create_schema()

    def close(self):
        if self.connection:
            self.connection.close()
            self.connection = None

    def _create_schema(self):
        self.connection.executescript(
            """
            PRAGMA foreign_keys=ON;
            CREATE TABLE IF NOT EXISTS demo_design(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              equipment_id TEXT NOT NULL,
              product_type TEXT NOT NULL,
              dn REAL NOT NULL,
              status TEXT NOT NULL DEFAULT '审核中',
              current_stage TEXT NOT NULL DEFAULT '管板型式',
              version INTEGER NOT NULL DEFAULT 1,
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS stage_review(
              design_id INTEGER NOT NULL,
              stage TEXT NOT NULL,
              payload_json TEXT NOT NULL,
              approved_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              PRIMARY KEY(design_id, stage),
              FOREIGN KEY(design_id) REFERENCES demo_design(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS source_document(
              design_id INTEGER NOT NULL,
              file_name TEXT NOT NULL,
              file_hash TEXT NOT NULL,
              status TEXT NOT NULL,
              evidence_json TEXT NOT NULL DEFAULT '[]'
            );
            CREATE TABLE IF NOT EXISTS audit_event(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              design_id INTEGER NOT NULL,
              event_type TEXT NOT NULL,
              detail_json TEXT NOT NULL,
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        self.connection.commit()

    def load_base_context(self, product_type: str, dn: float) -> dict:
        return deepcopy(_seed_context(product_type, dn))

    def lookup_history(self, product_type: str, dn: float) -> list[dict]:
        kind = (product_type or "").upper()
        ranked = sorted((r for r in HISTORY if r["product_type"] == kind), key=lambda r: abs(float(r["dn"]) - float(dn or 0)))
        return [dict(row, source="历史建议值") for row in ranked]

    def create_design(self, equipment_id: str, product_type: str, dn: float, documents=None) -> dict:
        with self.connection:
            cur = self.connection.execute(
                "INSERT INTO demo_design(equipment_id,product_type,dn) VALUES(?,?,?)",
                (equipment_id, product_type, float(dn)),
            )
            design_id = cur.lastrowid
            for document in documents or []:
                self.connection.execute(
                    "INSERT INTO source_document(design_id,file_name,file_hash,status,evidence_json) VALUES(?,?,?,?,?)",
                    (design_id, document.name, document.sha256, document.status, "[]"),
                )
            self._event(design_id, "创建设计", {"equipment_id": equipment_id, "source_count": len(documents or [])})
        return self.get_design(design_id)

    def get_design(self, design_id: int) -> dict:
        row = self.connection.execute("SELECT * FROM demo_design WHERE id=?", (design_id,)).fetchone()
        if not row:
            raise KeyError(f"设计 {design_id} 不存在")
        return dict(row)

    def save_stage(self, design_id: int, stage: str, payload: dict, expected_version: int) -> int:
        if stage not in STAGES:
            raise ValueError("未知审核阶段")
        with self.connection:
            row = self.connection.execute("SELECT version,status FROM demo_design WHERE id=?", (design_id,)).fetchone()
            if not row:
                raise KeyError(f"设计 {design_id} 不存在")
            if int(row["version"]) != int(expected_version):
                raise VersionConflict("设计已被其他操作更新，请重新打开后再保存")
            if row["status"] == "已完成":
                raise ValueError("已完成方案不能覆盖，请复制为新版本")
            self.connection.execute(
                "INSERT INTO stage_review(design_id,stage,payload_json) VALUES(?,?,?) "
                "ON CONFLICT(design_id,stage) DO UPDATE SET payload_json=excluded.payload_json,approved_at=CURRENT_TIMESTAMP",
                (design_id, stage, json.dumps(payload, ensure_ascii=False)),
            )
            next_index = min(STAGES.index(stage) + 1, len(STAGES) - 1)
            next_stage = STAGES[next_index]
            new_version = int(expected_version) + 1
            self.connection.execute(
                "UPDATE demo_design SET current_stage=?,version=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (next_stage, new_version, design_id),
            )
            self._event(design_id, "阶段确认", {"stage": stage, "version": new_version})
        return new_version

    def load_stage(self, design_id: int, stage: str) -> dict | None:
        row = self.connection.execute(
            "SELECT payload_json FROM stage_review WHERE design_id=? AND stage=?", (design_id, stage)
        ).fetchone()
        return json.loads(row[0]) if row else None

    def list_sources(self, design_id: int) -> list[dict]:
        return [dict(row) for row in self.connection.execute(
            "SELECT file_name,file_hash,status,evidence_json FROM source_document WHERE design_id=? ORDER BY file_name",
            (design_id,),
        ).fetchall()]

    def list_designs(self) -> list[dict]:
        return [dict(row) for row in self.connection.execute(
            "SELECT * FROM demo_design ORDER BY updated_at DESC,id DESC"
        ).fetchall()]

    def load_design_snapshot(self, design_id: int) -> dict:
        return {
            "design": self.get_design(design_id),
            "stages": {stage: self.load_stage(design_id, stage) for stage in STAGES},
            "sources": self.list_sources(design_id),
        }

    def clone_design(self, design_id: int) -> dict:
        source = self.get_design(design_id)
        clone = self.create_design(source["equipment_id"], source["product_type"], source["dn"])
        with self.connection:
            self.connection.execute(
                "INSERT INTO source_document(design_id,file_name,file_hash,status,evidence_json) "
                "SELECT ?,file_name,file_hash,status,evidence_json FROM source_document WHERE design_id=?",
                (clone["id"], design_id),
            )
            self._event(clone["id"], "复制历史方案", {"source_design_id": design_id})
        return self.get_design(clone["id"])

    def clear_stages_from(self, design_id: int, stage: str, expected_version: int) -> int:
        if stage not in STAGES:
            raise ValueError("未知审核阶段")
        index = STAGES.index(stage)
        targets = STAGES[index:]
        with self.connection:
            row = self.connection.execute("SELECT version,status FROM demo_design WHERE id=?", (design_id,)).fetchone()
            if not row or int(row["version"]) != int(expected_version):
                raise VersionConflict("设计版本已变化")
            placeholders = ",".join("?" for _ in targets)
            self.connection.execute(
                f"DELETE FROM stage_review WHERE design_id=? AND stage IN ({placeholders})",
                (design_id, *targets),
            )
            new_version = int(expected_version) + 1
            self.connection.execute(
                "UPDATE demo_design SET status='审核中',current_stage=?,version=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (stage, new_version, design_id),
            )
            self._event(design_id, "撤销下游审核", {"from_stage": stage, "version": new_version})
        return new_version

    def finalize_design(self, design_id: int, expected_version: int) -> int:
        with self.connection:
            row = self.connection.execute("SELECT version,status FROM demo_design WHERE id=?", (design_id,)).fetchone()
            if not row:
                raise KeyError(f"设计 {design_id} 不存在")
            if int(row["version"]) != int(expected_version):
                raise VersionConflict("设计版本已变化")
            count = self.connection.execute("SELECT COUNT(*) FROM stage_review WHERE design_id=?", (design_id,)).fetchone()[0]
            if count != len(STAGES):
                raise ValueError("四个阶段尚未全部确认，不能完成设计")
            new_version = int(expected_version) + 1
            self.connection.execute(
                "UPDATE demo_design SET status='已完成',version=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (new_version, design_id),
            )
            self._event(design_id, "完成设计", {"version": new_version})
        return new_version

    def _event(self, design_id: int, event_type: str, detail: dict[str, Any]):
        self.connection.execute(
            "INSERT INTO audit_event(design_id,event_type,detail_json) VALUES(?,?,?)",
            (design_id, event_type, json.dumps(detail, ensure_ascii=False)),
        )
