"""Entry point for the independent tube-bundle review agent demo."""
import argparse
import os
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description="管束AI审核助手Demo")
    parser.add_argument("--demo", action="store_true", help="打开离线演示数据")
    parser.add_argument("--screenshot", help="保存离线演示截图后退出")
    args = parser.parse_args()
    if args.screenshot:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt5.QtCore import QTimer
    from PyQt5.QtGui import QFont, QFontDatabase
    from PyQt5.QtWidgets import QApplication
    from document_reader import DocumentBundle
    from window import DesignWindow

    app = QApplication(sys.argv[:1])
    if os.name == "nt":
        font = Path(os.environ.get("SystemRoot", "C:/Windows")) / "Fonts" / "msyh.ttc"
        if font.exists():
            QFontDatabase.addApplicationFont(str(font))
    app.setFont(QFont("Microsoft YaHei", 10))
    window = DesignWindow()
    if args.screenshot:
        window.show()
    else:
        window.showMaximized()

    if args.demo or args.screenshot:
        window.start_with_bundle(DocumentBundle([]), "E-1001", "AEU", 700)
        window.run_review()
    if args.screenshot:
        def save_and_exit():
            path = Path(args.screenshot).resolve()
            path.parent.mkdir(parents=True, exist_ok=True)
            ok = window.grab().save(str(path))
            print(f"Review demo screenshot: {path}")
            print("Stage: 管板型式; validation passed; waiting for user confirmation")
            app.exit(0 if ok else 1)
        QTimer.singleShot(300, save_and_exit)
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
