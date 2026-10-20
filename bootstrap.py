"""Resolve the sibling source project without copying its database/UI/DLL stack."""
import os
from pathlib import Path
import sys

SOURCE = Path(os.environ.get('DONG_LANPEC_SOURCE') or Path(__file__).resolve().parent.parent / 'DongLanpec')
if not (SOURCE / 'modules/buguan/buguan_ziyong/tube_pass/adapter.py').is_file():
    raise RuntimeError('未找到同级DongLanpec工程，请把Demo与DongLanpec放在同一目录。')
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))
