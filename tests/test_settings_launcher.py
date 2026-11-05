import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from settings import save_settings, load_settings
from ai_support.api_client import APIConfig, DEEPSEEK_BASE_URL


@unittest.skipUnless(os.name=='nt','Windows launcher and account encryption')
class SettingsLauncherTests(unittest.TestCase):
    def test_old_bailian_settings_are_not_reused_as_deepseek_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'settings.json'
            target.write_text(json.dumps({
                'base_url': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
                'model': 'qwen-plus',
                'encrypted_key': 'not-a-deepseek-key',
            }), encoding='utf-8')
            config = load_settings(target)
            self.assertEqual(config.base_url, DEEPSEEK_BASE_URL)
            self.assertEqual(config.model, 'deepseek-v4-flash')
            self.assertFalse(config.configured)

    def test_windows_remembered_key_roundtrips_without_plaintext_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/'settings.json'
            config=APIConfig(DEEPSEEK_BASE_URL,'test-only-dummy-key','deepseek-v4-flash')
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
            result=subprocess.run([os.environ['COMSPEC'],'/d','/c',str(launcher),'--screenshot',str(target),'--stage','0'],
                env=env,cwd=tmp,capture_output=True,input='\n',encoding='utf-8',errors='replace',timeout=25)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertEqual(target.read_bytes()[:8],b'\x89PNG\r\n\x1a\n')
            self.assertIn('stage: 管板型式',result.stdout)


if __name__=='__main__':unittest.main()
