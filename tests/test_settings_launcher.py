import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from settings import save_settings,load_settings
from modules.buguan.buguan_ziyong.ai_assistant.api_client import APIConfig


@unittest.skipUnless(os.name=='nt','Windows launcher and account encryption')
class SettingsLauncherTests(unittest.TestCase):
    def test_windows_remembered_key_roundtrips_without_plaintext_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/'settings.json'
            config=APIConfig('https://dashscope.aliyuncs.com/compatible-mode/v1','test-only-dummy-key','qwen-plus')
            save_settings(config,True,target)
            self.assertNotIn('test-only-dummy-key',target.read_text(encoding='utf-8'))
            self.assertEqual(load_settings(target).api_key,'test-only-dummy-key')
            save_settings(config,False,target)
            self.assertNotIn('encrypted_key',json.loads(target.read_text(encoding='utf-8')))

    def test_actual_cmd_starts_complete_offline_workflow_from_another_directory(self):
        launcher=Path(__file__).resolve().parents[1]/'启动管束设计助手.cmd'
        with tempfile.TemporaryDirectory(prefix='designer demo ') as tmp:
            target=Path(tmp)/'screen with spaces.png'
            env=dict(os.environ,DONG_LANPEC_PYTHON=sys.executable,QT_QPA_PLATFORM='offscreen')
            result=subprocess.run([os.environ['COMSPEC'],'/d','/c',str(launcher),'--screenshot',str(target)],
                env=env,cwd=tmp,capture_output=True,input='\n',encoding='utf-8',errors='replace',timeout=25)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertEqual(target.read_bytes()[:8],b'\x89PNG\r\n\x1a\n')
            self.assertIn('Components: 11',result.stdout)


if __name__=='__main__':unittest.main()
