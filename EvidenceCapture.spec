# Build a single Windows executable; system Chinese fonts are embedded at export time.
from pathlib import Path

root = Path(SPECPATH)
a = Analysis(
    [str(root / 'EvidenceCapture.py')],
    pathex=[str(root)], binaries=[], datas=[],
    hiddenimports=['mss.windows', 'pyautogui._pyautogui_win', 'PIL.PngImagePlugin',
                   'reportlab.pdfbase._fontdata_enc_winansi'],
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=['numpy', 'pandas', 'cv2', 'matplotlib', 'IPython', 'pytest',
              'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'PySide6.QtQml',
              'PySide6.QtQuick', 'PySide6.QtMultimedia'],
    noarchive=False,
)
# Qt uses the unversioned ICU API supplied by Windows 10 1809+.
# A developer PATH containing Poppler/Conda may fool dependency discovery into
# bundling a different icuuc.dll (version-suffixed symbols), breaking QtCore import.
# Do not ship those unrelated DLLs or copy Windows system binaries.
a.binaries = [entry for entry in a.binaries if not Path(entry[0]).name.lower().startswith('icu')]
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name='聊天软件截屏助手', debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, console=False, disable_windowed_traceback=False,
    manifest=str(root / 'assets' / 'app.manifest'),
    icon=str(root / 'assets' / 'app.ico'),
)
