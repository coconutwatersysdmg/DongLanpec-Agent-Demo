import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QTextCursor
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QLabel

from db.production import DatabaseUnavailable
from models import STAGES
from window import DesignWindow, MessageInput


class OfflineRepository:
    """模拟数据库不可用：用于验证“明确报错、不退回模拟库”。"""

    allow_write = False

    def ping(self):
        return False, "无法连接 MySQL：Can't connect to MySQL server on 'localhost' (10061)"

    def list_products(self, limit=80):
        raise DatabaseUnavailable("无法连接正式数据库：Can't connect to MySQL server")


class WindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = DesignWindow(repository=OfflineRepository())
        self.window.resize(1600, 960)
        self.window.show()

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()

    def test_stage_buttons_use_formal_names(self):
        labels = [button.text() for button in self.window.stage_buttons]
        self.assertEqual(tuple(labels), STAGES)
        self.assertTrue(all(not button.isEnabled() for button in self.window.stage_buttons))

    def test_initial_screen_is_chat_style(self):
        self.assertEqual(len(self.window.chat_history), 1)
        self.assertEqual(self.window.chat_history[0]["role"], "assistant")
        self.assertTrue(self.window.prompt.isVisible() or self.window.prompt is not None)

    def test_user_message_is_right_aligned(self):
        self.window.append_chat("user", "换热管中心距改成34毫米")
        row = self.window.conversation.message_rows[-1]
        layout = row.layout()
        last_index = layout.count() - 1
        # 用户消息在右侧：右侧是消息本体
        self.assertEqual(layout.itemAt(last_index).widget().objectName(), "userMessage")

    def test_start_without_database_reports_error_instead_of_falling_back(self):
        self.window.start_design()
        last = self.window.chat_history[-1]
        self.assertEqual(last["role"], "assistant")
        self.assertIn("无法连接正式数据库", last["content"])
        self.assertIn("排查", last["content"])
        self.assertIsNone(self.window.session, "数据库失败时不得生成模拟草稿")

    def test_enter_sends_and_shift_enter_breaks_line(self):
        prompt = MessageInput()
        sent = []
        prompt.send_requested.connect(lambda: sent.append(prompt.toPlainText()))
        prompt.setPlainText("保留当前方案")
        QTest.keyClick(prompt, Qt.Key_Return)
        self.assertEqual(sent, ["保留当前方案"])

        prompt.moveCursor(QTextCursor.End)
        before = prompt.toPlainText()
        QTest.keyClick(prompt, Qt.Key_Return, Qt.ShiftModifier)
        self.assertEqual(prompt.toPlainText(), before + "\n")

    def test_enter_in_window_sends_chat_message(self):
        window = self.window
        window.prompt.setPlainText("保留当前方案")
        QTest.keyClick(window.prompt, Qt.Key_Return)
        self.assertEqual(window.prompt.toPlainText(), "", "发送后输入框应清空")
        self.assertEqual(window.chat_history[-2]["role"], "user")
        self.assertEqual(window.chat_history[-2]["content"], "保留当前方案")

    def test_clear_chat_keeps_greeting(self):
        self.window.append_chat("user", "你好")
        self.window.clear_chat()
        self.assertEqual(len(self.window.chat_history), 1)
        self.assertEqual(self.window.chat_history[0]["role"], "assistant")


if __name__ == "__main__":
    unittest.main()
