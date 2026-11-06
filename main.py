"""管束设计 Agent Demo 启动入口。

用法：
    python main.py                         正常启动图形界面
    python main.py --screenshot out.png    离屏渲染截图后退出（用于验收留证）
        可选 --stage 0..3      指定截图时展开的 Tab
                               0 管板型式 / 1 布管 / 2 管-板连接 / 3 轴向设计
        可选 --product 产品ID  指定载入的产品，缺省取数据库第一条
"""
import argparse
import os
from pathlib import Path
import sys


def _install_font(app):
    from PyQt5.QtGui import QFont, QFontDatabase

    if os.name == "nt":
        fonts_dir = Path(os.environ.get("SystemRoot", "C:/Windows")) / "Fonts"
        for filename in ("msyh.ttc", "msyhbd.ttc"):
            path = fonts_dir / filename
            if path.exists():
                QFontDatabase.addApplicationFont(str(path))
    app.setFont(QFont("Microsoft YaHei UI", 10))


def main():
    parser = argparse.ArgumentParser(description="管束设计 Agent Demo")
    parser.add_argument("--screenshot", help="离屏渲染界面截图并保存到该路径，随后退出")
    parser.add_argument("--stage", type=int, default=None, help="截图前展开的 Tab 序号 0-3")
    parser.add_argument("--product", default=None, help="指定要载入的产品ID")
    parser.add_argument("--width", type=int, default=1920, help="截图窗口宽度")
    parser.add_argument("--height", type=int, default=1040, help="截图窗口高度")
    args = parser.parse_args()

    if args.screenshot:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PyQt5.QtCore import QTimer
    from PyQt5.QtWidgets import QApplication

    app = QApplication(sys.argv[:1])
    _install_font(app)

    from window import DesignWindow

    window = DesignWindow()
    if args.screenshot:
        window.resize(args.width, args.height)
        window.show()
    else:
        # 正常启动直接铺满屏幕：对话是主界面，越大越好（仍可点右上角还原）
        window.showMaximized()

    if args.screenshot:
        # 离屏截图不需要事件循环：同步载入会话、展开 Tab、抓图后立即退出。
        from models import STAGES

        window.headless = True  # 跳过模态确认框，且只生成写库计划、不写正式库
        for _ in range(3):
            app.processEvents()
        if args.stage is None:
            # 未指定 Tab：截取初始聊天界面（不建会话）
            path = Path(args.screenshot).resolve()
            path.parent.mkdir(parents=True, exist_ok=True)
            ok = window.grab().save(str(path))
            print(f"screenshot: {path}（初始聊天界面）ok={ok}")
            return 0 if ok else 1
        stage = max(0, min(len(STAGES) - 1, args.stage))
        try:
            window._boot_session(args.product)
            for index in range(stage):
                window.open_stage(index)
                window.keep_current(STAGES[index])
                app.processEvents()
            window.open_stage(stage)
        except Exception as exc:  # noqa: BLE001
            print(f"[screenshot] 载入会话失败：{type(exc).__name__}: {exc}")
        for _ in range(5):
            app.processEvents()
        # 滚到卡片底部，保证截图里能看到唯一的“保留”按钮
        window.conversation._scroll_to_bottom()
        app.processEvents()
        path = Path(args.screenshot).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        pixmap = window.grab()
        ok = pixmap.save(str(path))
        print(f"screenshot: {path} ({pixmap.width()}x{pixmap.height()}) ok={ok}")
        if window.session is not None:
            print(f"session: {window.session.header_text()}")
            print(f"stage: {STAGES[stage]}")
        return 0 if ok else 1

    app.processEvents()
    QTimer.singleShot(0, lambda: None)
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
