from __future__ import annotations

import hashlib
import io
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import fitz
from openpyxl import load_workbook

from models import Evidence


MAX_FILE_BYTES = 30 * 1024 * 1024
MAX_PART_CHARS = 12000
MAX_ZIP_ENTRIES = 200
EQUIPMENT_RE = re.compile(r"\b[A-Z]{2,}(?:-[A-Z0-9]+){2,}(?:/[A-Z])?\b", re.I)
PREFERRED_EQUIPMENT_RE = re.compile(
    r"\b(?:OST-(?:E|EH)-\d{3,5}(?:-\d+)?[A-Z]{0,2}(?:/[A-Z])?|OST-WC-?\d{3,5}[A-Z]{0,2}(?:/[A-Z])?)\b",
    re.I,
)


@dataclass
class DocumentPart:
    file_name: str
    source_ref: str
    text: str


@dataclass
class DocumentRecord:
    name: str
    status: str
    sha256: str
    parts: list[DocumentPart] = field(default_factory=list)


@dataclass
class DocumentBundle:
    documents: list[DocumentRecord]

    @property
    def parts(self):
        return [part for document in self.documents for part in document.parts]


def _clean(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _pdf_parts(data: bytes, name: str) -> list[DocumentPart]:
    parts = []
    with fitz.open(stream=data, filetype="pdf") as document:
        for page_index, page in enumerate(document):
            text = _clean(page.get_text("text"))[:MAX_PART_CHARS]
            if text:
                parts.append(DocumentPart(name, f"{name} 第{page_index + 1}页", text))
    return parts


def _xlsx_parts(data: bytes, name: str) -> list[DocumentPart]:
    parts = []
    workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    try:
        for sheet in workbook.worksheets:
            for row_index, row in enumerate(sheet.iter_rows(values_only=True), 1):
                text = _clean(" | ".join(str(cell) for cell in row if cell not in (None, "")))
                if text:
                    parts.append(DocumentPart(name, f"{name} 工作表“{sheet.title}”第{row_index}行", text[:MAX_PART_CHARS]))
    finally:
        workbook.close()
    return parts


def _record(data: bytes, name: str) -> DocumentRecord:
    suffix = Path(name).suffix.lower()
    if len(data) > MAX_FILE_BYTES:
        return DocumentRecord(name, "文件过大，未解析", _hash(data))
    try:
        if suffix == ".pdf":
            return DocumentRecord(name, "已解析", _hash(data), _pdf_parts(data, name))
        if suffix in {".xlsx", ".xlsm"}:
            return DocumentRecord(name, "已解析", _hash(data), _xlsx_parts(data, name))
        if suffix == ".doc":
            return DocumentRecord(name, "旧版DOC需转换后解析", _hash(data))
        if suffix == ".docx":
            return DocumentRecord(name, "DOCX暂不参与本轮提取", _hash(data))
        return DocumentRecord(name, "非管束文本文件，已跳过", _hash(data))
    except Exception as exc:
        return DocumentRecord(name, f"解析失败：{type(exc).__name__}", _hash(data))


def scan_inputs(paths) -> DocumentBundle:
    documents: list[DocumentRecord] = []
    for raw_path in paths:
        path = Path(raw_path)
        if path.suffix.lower() == ".zip":
            try:
                with zipfile.ZipFile(path) as archive:
                    for info in archive.infolist()[:MAX_ZIP_ENTRIES]:
                        if info.is_dir():
                            continue
                        safe_name = Path(info.filename.replace("\\", "/")).name
                        if not safe_name:
                            continue
                        if info.file_size > MAX_FILE_BYTES:
                            documents.append(DocumentRecord(f"{path.name}/{safe_name}", "文件过大，未解析", ""))
                            continue
                        data = archive.read(info)
                        record = _record(data, f"{path.name}/{safe_name}")
                        documents.append(record)
            except (OSError, zipfile.BadZipFile):
                documents.append(DocumentRecord(path.name, "压缩包损坏或无法读取", ""))
        else:
            try:
                documents.append(_record(path.read_bytes(), path.name))
            except OSError:
                documents.append(DocumentRecord(path.name, "文件无法读取", ""))
    return DocumentBundle(documents)


def _expand_equipment(token: str) -> list[str]:
    token = token.upper()
    if "/" not in token:
        if re.search(r"\dAB$", token):
            return [token[:-2] + "A", token[:-2] + "B"]
        return [token]
    base, suffix = token.split("/", 1)
    if suffix and len(suffix) == 1 and base[-1:].isalpha():
        return [base, base[:-1] + suffix]
    return [token]


def identify_equipment(bundle: DocumentBundle) -> list[str]:
    found, preferred = set(), set()
    for part in bundle.parts:
        for token in EQUIPMENT_RE.findall(part.text.upper()):
            found.update(_expand_equipment(token))
        for token in PREFERRED_EQUIPMENT_RE.findall(part.text.upper()):
            preferred.update(_expand_equipment(token))
    return sorted(preferred or found)


def retrieve(bundle: DocumentBundle, equipment_id: str, keywords, limit=40) -> list[Evidence]:
    target = (equipment_id or "").upper().strip()
    normalized_keywords = [str(k).lower().strip() for k in keywords if str(k).strip()]
    ranked = []
    common_markers = ("通用要求", "统一规定", "所有换热器", "全部换热器", "general requirement", "all heat exchangers")
    for part in bundle.parts:
        upper = part.text.upper()
        matches = list(EQUIPMENT_RE.finditer(upper))
        excerpts = []
        if matches:
            for index, match in enumerate(matches):
                expanded = _expand_equipment(match.group(0))
                if target not in expanded:
                    continue
                end = matches[index + 1].start() if index + 1 < len(matches) else len(part.text)
                excerpts.append(part.text[match.start():end].strip(" |;，。"))
        elif any(marker in part.text.lower() for marker in common_markers):
            excerpts.append(part.text)
        else:
            # Untagged continuation rows are not safe to attribute to one device.
            continue
        for excerpt in excerpts:
            keyword_hits = sum(1 for keyword in normalized_keywords if keyword in excerpt.lower())
            if keyword_hits == 0 and target not in excerpt.upper():
                continue
            score = (20 if target in excerpt.upper() else 0) + keyword_hits
            ranked.append((score, part.source_ref, part, excerpt))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return [
        Evidence(part.source_ref, excerpt, part.file_name, target)
        for _score, _ref, part, excerpt in ranked[: max(1, int(limit))]
    ]
