"""Optional Windows-account encrypted credentials; no plaintext key files."""
import base64
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import bootstrap
from ai_support.api_client import APIConfig, BAILIAN_BASE_URL

CONFIG_PATH=Path(os.environ.get('APPDATA') or Path.home())/'DongLanpecAgentDemo'/'settings.json'


def protect(data:bytes,decrypt=False):
    if os.name!='nt':raise ValueError('仅Windows支持本机账户加密记住密钥')
    class Blob(ctypes.Structure):
        _fields_=[('size',wintypes.DWORD),('data',ctypes.POINTER(ctypes.c_ubyte))]
    buffer=ctypes.create_string_buffer(data)
    source=Blob(len(data),ctypes.cast(buffer,ctypes.POINTER(ctypes.c_ubyte)))
    target=Blob()
    fn=ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
    if not fn(ctypes.byref(source),None,None,None,None,1,ctypes.byref(target)):
        raise ValueError('Windows账户加密操作失败，请先取消“记住密钥”继续使用')
    try:return ctypes.string_at(target.data,target.size)
    finally:
        free=ctypes.windll.kernel32.LocalFree
        free.argtypes=[ctypes.c_void_p];free.restype=ctypes.c_void_p
        free(ctypes.cast(target.data,ctypes.c_void_p))


def load_settings(path=CONFIG_PATH):
    try:
        data=json.loads(Path(path).read_text(encoding='utf-8'))
        if not isinstance(data,dict):data={}
    except (OSError,ValueError):data={}
    key=os.environ.get('DASHSCOPE_API_KEY') or os.environ.get('DONG_LANPEC_AI_API_KEY') or ''
    if data.get('encrypted_key'):
        try:key=protect(base64.b64decode(data['encrypted_key']),decrypt=True).decode('utf-8')
        except Exception:pass
    return APIConfig(str(data.get('base_url') or BAILIAN_BASE_URL),key,str(data.get('model') or 'qwen-plus'))


def save_settings(config,remember,path=CONFIG_PATH):
    config.endpoint()
    if not config.configured:raise ValueError('请填写完整的百炼API Key')
    data={'base_url':config.base_url,'model':config.model}
    if remember:data['encrypted_key']=base64.b64encode(protect(config.api_key.encode('utf-8'))).decode('ascii')
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')


def settings_dialog(parent,config):
    from PyQt5.QtWidgets import (QDialog,QVBoxLayout,QFormLayout,QLabel,QLineEdit,QCheckBox,
                                  QDialogButtonBox,QMessageBox,QWidget)
    dialog=QDialog(parent);dialog.setWindowTitle('AI设置');dialog.resize(570,260)
    root=QVBoxLayout(dialog)
    root.addWidget(QLabel('把阿里云百炼的完整API Key粘贴到下面，保存后即可使用。'))
    key=QLineEdit(config.api_key);key.setEchoMode(QLineEdit.Password)
    key.setPlaceholderText('百炼API Key（不是阿里云AccessKey）')
    form=QFormLayout();form.addRow('API Key',key);root.addLayout(form)
    remember=QCheckBox('记住密钥（使用当前Windows账户加密保存）')
    remember.setChecked(os.name=='nt');remember.setEnabled(os.name=='nt');root.addWidget(remember)
    advanced=QCheckBox('更多设置（通常无需修改）');root.addWidget(advanced)
    box=QWidget();extra=QFormLayout(box)
    base=QLineEdit(config.base_url);model=QLineEdit(config.model)
    extra.addRow('服务地址',base);extra.addRow('模型',model);box.hide();root.addWidget(box)
    advanced.toggled.connect(box.setVisible)
    note=QLabel('默认使用北京地域与qwen-plus。其他地域请在更多设置中修改地址。\n保存设置不调用模型，点击“开始设计”才会联网。')
    note.setWordWrap(True);root.addWidget(note)
    buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel)
    buttons.button(QDialogButtonBox.Save).setText('保存并返回')
    buttons.button(QDialogButtonBox.Cancel).setText('取消');root.addWidget(buttons)
    chosen=[]
    def save():
        candidate=APIConfig(base.text().strip(),key.text().strip(),model.text().strip())
        try:save_settings(candidate,remember.isChecked())
        except (ValueError,OSError):
            QMessageBox.warning(dialog,'设置未保存','请检查密钥及服务地址；如无法记住密钥，可取消勾选后重试。');return
        chosen.append(candidate);dialog.accept()
    buttons.accepted.connect(save);buttons.rejected.connect(dialog.reject)
    return chosen[0] if dialog.exec_()==QDialog.Accepted else config
