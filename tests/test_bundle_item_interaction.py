import unittest

from PyQt5.QtCore import QRectF, Qt

from bundle.items import ComponentRectItem


class _DoubleClickEvent:
    def button(self):
        return Qt.LeftButton

    def accept(self):
        self.accepted = True


class _Controller:
    def __init__(self):
        self.edited_item = None

    def item_double_clicked(self, item):
        self.edited_item = item


class ComponentDoubleClickTests(unittest.TestCase):
    def test_double_click_routes_component_to_controller(self):
        controller = _Controller()
        item = ComponentRectItem(QRectF(0, 0, 10, 4), controller)
        item.component_index = 2
        event = _DoubleClickEvent()

        item.mouseDoubleClickEvent(event)

        self.assertIs(controller.edited_item, item)
        self.assertTrue(event.accepted)


if __name__ == "__main__":
    unittest.main()
