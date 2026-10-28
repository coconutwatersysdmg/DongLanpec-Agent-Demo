import io
import tempfile
import unittest
import zipfile
from pathlib import Path

import fitz
from openpyxl import Workbook

from document_reader import DocumentBundle, DocumentPart, DocumentRecord, identify_equipment, retrieve, scan_inputs


def pdf_bytes(pages):
    doc = fitz.open()
    for text in pages:
        page = doc.new_page()
        page.insert_text((50, 80), text, fontname="china-s")
    data = doc.tobytes()
    doc.close()
    return data


def xlsx_bytes(rows):
    wb = Workbook()
    ws = wb.active
    ws.title = "答复"
    for row in rows:
        ws.append(row)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


class DocumentReaderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.zip_path = self.root / "inputs.zip"
        with zipfile.ZipFile(self.zip_path, "w") as archive:
            archive.writestr("datasheet.pdf", pdf_bytes([
                "OST-E-1903A U-tube count 675, tube-hole count 1350, outside diameter 19 mm",
                "OST-E-1904A BES tube count 366, outside diameter 25 mm",
            ]))
            archive.writestr("reply.xlsx", xlsx_bytes([
                ["OST-E-1904A", "actual tube count 360"],
                ["OST-E-1903A", "Should baffle type be single segmental or double segmental?"],
            ]))
            archive.writestr("legacy.doc", b"old-binary-doc")

    def tearDown(self):
        self.tmp.cleanup()

    def test_zip_scan_identifies_multiple_equipment_and_unsupported_doc(self):
        bundle = scan_inputs([self.zip_path])
        equipment = identify_equipment(bundle)
        self.assertIn("OST-E-1903A", equipment)
        self.assertIn("OST-E-1904A", equipment)
        legacy = next(d for d in bundle.documents if d.name.endswith("legacy.doc"))
        self.assertEqual(legacy.status, "旧版DOC需转换后解析")

    def test_document_numbers_are_hidden_when_real_equipment_candidates_exist(self):
        record = DocumentRecord("x", "已解析", "x", [
            DocumentPart("x", "x 第1页", "DD-DDS-OST-PR-19001 for OST-E-1904A and OST-E-1904B"),
        ])
        equipment = identify_equipment(DocumentBundle([record]))
        self.assertEqual(equipment, ["OST-E-1904A", "OST-E-1904B"])

    def test_retrieve_isolates_selected_equipment(self):
        bundle = scan_inputs([self.zip_path])
        evidence = retrieve(bundle, "OST-E-1904A", ["tube", "outside"], 20)
        text = "\n".join(item.excerpt for item in evidence)
        self.assertIn("1904A", text)
        self.assertNotIn("1903A", text)

    def test_page_and_sheet_references_are_preserved(self):
        bundle = scan_inputs([self.zip_path])
        evidence = retrieve(bundle, "OST-E-1904A", ["tube"], 20)
        refs = [item.source_ref for item in evidence]
        self.assertTrue(any("第2页" in ref for ref in refs), refs)
        self.assertTrue(any("工作表“答复”" in ref for ref in refs), refs)

    def test_tube_and_tube_hole_wording_remain_distinct(self):
        bundle = scan_inputs([self.zip_path])
        evidence = retrieve(bundle, "OST-E-1903A", ["count"], 20)
        text = " ".join(item.excerpt for item in evidence)
        self.assertIn("U-tube count 675", text)
        self.assertIn("tube-hole count 1350", text)


if __name__ == "__main__":
    unittest.main()
