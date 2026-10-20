"""Entry point for the sibling tube-design agent demo."""
import argparse
import os
from pathlib import Path
import sys


def main():
    parser=argparse.ArgumentParser(description='管束设计助手Demo')
    parser.add_argument('--demo',action='store_true',help='打开并执行固定操作演示，不联网')
    parser.add_argument('--screenshot',help='执行固定操作演示并保存界面截图后退出，不联网')
    args=parser.parse_args()
    if args.screenshot:os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    from PyQt5.QtWidgets import QApplication
    from PyQt5.QtGui import QFont,QFontDatabase
    from PyQt5.QtCore import QTimer
    from window import DesignWindow
    from engine import EXAMPLE_TEXT
    app=QApplication(sys.argv[:1])
    if args.screenshot and os.name=='nt':
        font=Path(os.environ.get('SystemRoot','C:/Windows'))/'Fonts'/'msyh.ttc'
        if font.exists():QFontDatabase.addApplicationFont(str(font))
    app.setFont(QFont('Microsoft YaHei',10))
    window=DesignWindow();window.show()
    if args.demo or args.screenshot:
        window.mode.setCurrentIndex(1);window.prompt.setPlainText(EXAMPLE_TEXT)
        QTimer.singleShot(0,window.start_agent)
    if args.screenshot:
        polls=[0]
        def save():
            polls[0]+=1
            if window.worker is not None or not window.engine.state['laid_out']:
                if polls[0]>200:app.exit(1)
                else:QTimer.singleShot(50,save)
                return
            path=Path(args.screenshot).resolve();path.parent.mkdir(parents=True,exist_ok=True)
            ok=window.grab().save(str(path))
            print('Offline demo screenshot:',path)
            print('Tube positions:',len(window.engine.state['tubes']),'Components:',len(window.engine.state['components']))
            app.exit(0 if ok else 1)
        QTimer.singleShot(100,save)
    return app.exec_()


if __name__=='__main__':raise SystemExit(main())
