import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def database_available() -> bool:
    try:
        sys.path.insert(0, str(ROOT))
        from db.production import ProductionRepository

        return ProductionRepository().ping()[0]
    except Exception:  # noqa: BLE001
        return False


@unittest.skipUnless(database_available(), "需要正式数据库（产品设计活动库）在线")
class AcceptanceTests(unittest.TestCase):
    """完整跑一遍：读库 → 四 Tab 草稿 → 图形/表格交互 → 保留 → 写库计划（不提交）。"""

    def test_acceptance_script_passes(self):
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONUTF8="1")
        result = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "acceptance_check.py")],
            cwd=str(ROOT), env=env, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=180,
        )
        self.assertEqual(result.returncode, 0, result.stdout[-4000:] + result.stderr[-2000:])
        self.assertIn("自检结果", result.stdout)
        self.assertNotIn("FAIL", result.stdout)


if __name__ == "__main__":
    unittest.main()
