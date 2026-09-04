from pathlib import Path

root = Path(SPECPATH)
a = Analysis(
    [str(root / 'license_admin' / 'EvidenceLicenseManager.py')],
    pathex=[str(root)], binaries=[],
    datas=[(str(root / 'license_admin' / 'license_private.pem'), '.')],
    hiddenimports=[], hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=['numpy', 'pandas', 'cv2', 'matplotlib', 'IPython', 'pytest',
              'PIL', 'mss', 'pyautogui', 'reportlab',
              'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'PySide6.QtQml',
              'PySide6.QtQuick', 'PySide6.QtMultimedia'],
    noarchive=False,
)
a.binaries = [entry for entry in a.binaries if not Path(entry[0]).name.lower().startswith('icu')]
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [], name='聊天软件截屏助手授权管理器',
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    console=False, disable_windowed_traceback=False,
    manifest=str(root / 'assets' / 'app.manifest'),
    icon=str(root / 'assets' / 'app.ico'),
)
