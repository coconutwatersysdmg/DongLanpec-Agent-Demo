import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest

from PyQt5.QtWidgets import QApplication

from db.production import SaveFailed
from models import STAGES
from session import DesignSession


class FakeRepository:
    """只记录调用，不连接数据库。"""

    def __init__(self):
        self.allow_write = False
        self.saved = []

    def explain_save(self, payload):
        return [f"DELETE {payload['product_id']}", "INSERT ..."]

    def save_design(self, payload, dry_run=False):
        self.saved.append((payload, dry_run))
        if not self.allow_write and not dry_run:
            raise SaveFailed("未获准写库")
        return {"executed": not dry_run, "statements": 2}


def payload(stage):
    return {"stage": stage, "parameters": {}, "hole_count": 1}


class SessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make(self):
        product = {"产品ID": "P1", "项目ID": "J1", "产品型式": "AEU"}
        return DesignSession(FakeRepository(), product, {"公称直径": {"value": "1000"}})

    def test_stage_names(self):
        self.assertEqual(STAGES, ("管板型式", "布管", "管-板连接", "轴向设计"))

    def test_any_tab_can_be_kept_without_prior_tab(self):
        session = self.make()
        for stage in STAGES:
            self.assertEqual(session.can_keep(stage), (True, ""))
        session.mark_kept("轴向设计", payload("轴向设计"))
        self.assertEqual(session.approved, [False, False, False, True])
        self.assertIn("轴向设计", session.payloads)

    def test_keep_navigates_forward_without_forcing_unkept_earlier_tab(self):
        session = self.make()
        session.current_index = 1

        session.mark_kept("布管", payload("布管"))

        self.assertEqual(session.approved, [False, True, False, False])
        self.assertEqual(session.current_index, 2)

    def test_rekeeping_one_tab_preserves_other_tabs(self):
        session = self.make()
        for stage in STAGES:
            session.mark_kept(stage, payload(stage))
        self.assertTrue(session.complete)
        session.mark_kept("管板型式", payload("管板型式"))
        self.assertEqual(session.approved, [True, True, True, True])
        self.assertIn("布管", session.payloads)

    def test_editing_one_tab_only_invalidates_that_tab(self):
        session = self.make()
        for stage in STAGES:
            session.mark_kept(stage, payload(stage))

        session.invalidate_stage("布管")

        self.assertEqual(session.approved, [True, False, True, True])
        self.assertNotIn("布管", session.payloads)
        self.assertIn("管-板连接", session.payloads)
        self.assertIn("轴向设计", session.payloads)

    def test_save_requires_all_stages(self):
        session = self.make()
        for stage in STAGES[:3]:
            session.mark_kept(stage, payload(stage))
        with self.assertRaises(SaveFailed):
            session.save(confirm=True)
        self.assertFalse(session.repository.allow_write)

    def test_dry_run_never_enables_write(self):
        session = self.make()
        for stage in STAGES:
            session.mark_kept(stage, payload(stage))
        result = session.save(confirm=False)
        self.assertFalse(result["executed"])
        self.assertFalse(session.repository.allow_write)
        self.assertTrue(session.repository.saved[-1][1], "dry_run 标志应为 True")

    def test_save_opens_write_only_after_confirmation(self):
        session = self.make()
        for stage in STAGES:
            session.mark_kept(stage, payload(stage))
        result = session.save(confirm=True)
        self.assertTrue(result["executed"])
        self.assertTrue(session.repository.allow_write)

    def test_layout_linkage_uses_dn_and_r2(self):
        session = self.make()
        self.assertEqual(session.layout_linkage({"R2": 8})["布管限定圆 DL"], "984")


if __name__ == "__main__":
    unittest.main()
