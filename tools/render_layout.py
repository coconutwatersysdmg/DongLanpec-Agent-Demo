"""离屏渲染脚本：把布管页面渲染成 PNG，便于人工核对图形/表格是否正确。

用法：
    python tools/render_layout.py out.png [--product PD...] [--rows 2]
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QTimer  # noqa: E402
from PyQt5.QtGui import QFont, QFontDatabase  # noqa: E402
from PyQt5.QtWidgets import QApplication, QVBoxLayout, QWidget  # noqa: E402

from bundle.page import TubeLayoutPage  # noqa: E402
from db.production import ProductionRepository  # noqa: E402


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "artifacts/layout.png")
    product_id = None
    for index, arg in enumerate(sys.argv):
        if arg == "--product" and index + 1 < len(sys.argv):
            product_id = sys.argv[index + 1]
    app = QApplication(sys.argv[:1])
    if os.name == "nt":
        font = Path(os.environ.get("SystemRoot", "C:/Windows")) / "Fonts" / "msyh.ttc"
        if font.exists():
            QFontDatabase.addApplicationFont(str(font))
    app.setFont(QFont("Microsoft YaHei UI", 10))

    repo = ProductionRepository()
    products = repo.list_products(20)
    product_id = product_id or products[0]["产品ID"]
    product = repo.product(product_id)
    params = repo.layout_params(product_id) or {}
    defaults = repo.layout_defaults(product["产品型式"])
    for name, value in defaults.items():
        params.setdefault(name, {"value": value, "unit": ""})
    sheet_form = {row["参数符号"]: row["默认值"] for row in repo.sheet_form("a") if row["参数符号"]}
    page = TubeLayoutPage(
        params, product["产品型式"], defaults,
        center_distance_rows=repo.center_distance_table(),
        sheet_form=sheet_form,
    )
    window = QWidget()
    window.setWindowTitle("布管预览")
    window.resize(1900, 1000)
    layout = QVBoxLayout(window)
    layout.setContentsMargins(10, 10, 10, 10)
    layout.addWidget(page)
    window.show()

    def shot():
        out.parent.mkdir(parents=True, exist_ok=True)
        ok = window.grab().save(str(out))
        print(f"saved={ok} path={out}")
        print(f"product={product_id} type={product['产品型式']}")
        print("\n".join(page.summary_lines()))
        print("issues:", page.validation_issues())
        app.exit(0 if ok else 1)

    QTimer.singleShot(600, shot)
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
