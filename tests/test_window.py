import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import time
import unittest
from unittest.mock import patch
from PyQt5.QtWidgets import (
    QApplication, QLabel, QGraphicsLineItem, QGraphicsRectItem, QTabWidget,
)
from PyQt5.QtTest import QTest
from window import DesignWindow
from engine import EXAMPLE_TEXT
from ai_support.api_client import APIConfig


class WindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.config_patch=patch('window.load_settings',return_value=APIConfig())
        self.config_patch.start();self.window=DesignWindow()

    def tearDown(self):self.window.close();self.window.deleteLater();self.config_patch.stop()

    def run_offline_example(self):
        self.window.prompt.setPlainText(EXAMPLE_TEXT)
        self.window.mode.setCurrentIndex(1)
        self.window.start_agent()
        deadline=time.monotonic()+8
        while self.window.worker is not None and time.monotonic()<deadline:QTest.qWait(20)
        self.assertIsNone(self.window.worker)

    def test_designer_can_run_one_instruction_and_undo_whole_run(self):
        self.run_offline_example()
        self.assertTrue(self.window.engine.state['laid_out'])
        self.assertEqual(len(self.window.engine.state['components']),11)
        self.assertGreater(self.window.row_table.rowCount(),0)
        self.assertFalse(self.window.details.isVisible())
        self.window.undo()
        self.assertFalse(self.window.engine.state['laid_out'])
        self.assertEqual(self.window.engine.state['parameters'],{})

    def test_manual_layout_before_parameters_gives_plain_missing_message(self):
        self.window.manual_layout()
        self.assertFalse(self.window.engine.state['laid_out'])
        self.assertIn('补充',self.window.status.text())

    def test_workspace_omits_redundant_explanatory_headings(self):
        visible_text='\n'.join(label.text() for label in self.window.findChildren(QLabel))
        for removed in (
            '参数、布管与元件布置', '布管与元件设计', '设计参数',
            '告诉我你要怎么设计，我来依次完成。',
            '可手动填参，也可以把设计要求交给右侧助手。',
        ):
            self.assertNotIn(removed,visible_text)
        self.assertEqual(self.window.findChildren(QTabWidget),[])

    def test_layout_uses_original_center_connections_and_component_colors(self):
        self.run_offline_example()
        items=self.window.canvas.scene().items()
        blue_connections=[
            item for item in items
            if isinstance(item,QGraphicsLineItem)
            and item.pen().color().name()=='#0000ff'
        ]
        self.assertGreater(len(blue_connections),100)
        rectangle_colors=[
            item.brush().color().name() for item in items
            if isinstance(item,QGraphicsRectItem)
        ]
        self.assertEqual(rectangle_colors.count('#0000ff'),2)
        self.assertEqual(rectangle_colors.count('#00008b'),1)


if __name__=='__main__':unittest.main()
