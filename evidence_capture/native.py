"""Windows adapter; all capture coordinates are physical pixels."""
from __future__ import annotations
import ctypes
import os
from ctypes import wintypes


def enable_dpi_awareness():
    if os.name != "nt":
        return
    try:
        if ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return
    except (AttributeError, OSError):
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        ctypes.windll.user32.SetProcessDPIAware()


def user32():
    lib = ctypes.WinDLL("user32", use_last_error=True)
    lib.WindowFromPoint.argtypes = [wintypes.POINT]
    lib.WindowFromPoint.restype = wintypes.HWND
    lib.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    lib.GetAncestor.restype = wintypes.HWND
    lib.GetForegroundWindow.restype = wintypes.HWND
    lib.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    lib.IsWindow.argtypes = [wintypes.HWND]
    lib.IsIconic.argtypes = [wintypes.HWND]
    lib.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    return lib


def escape_pressed() -> bool:
    return os.name == "nt" and bool(ctypes.windll.user32.GetAsyncKeyState(0x1B) & 0x8000)


def monitors() -> list[dict]:
    if os.name != "nt":
        import mss
        with mss.mss() as sct:
            return [dict(m, name=str(i)) for i, m in enumerate(sct.monitors[1:])]

    class MonitorInfo(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD),
                    ("szDevice", wintypes.WCHAR * 32)]

    result = []
    lib = user32()
    lib.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MonitorInfo)]
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HANDLE, wintypes.HDC,
                                     ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)

    def callback(handle, dc, rect, param):
        info = MonitorInfo()
        info.cbSize = ctypes.sizeof(info)
        if lib.GetMonitorInfoW(handle, ctypes.byref(info)):
            r = info.rcMonitor
            result.append(dict(name=info.szDevice, left=r.left, top=r.top,
                               width=r.right - r.left, height=r.bottom - r.top))
        return True

    cb = callback_type(callback)
    lib.EnumDisplayMonitors(None, None, cb, 0)
    return sorted(result, key=lambda m: m["name"])


class WindowGuard:
    """Stop on window movement/focus changes/occlusion at sampled region points."""
    def __init__(self, region):
        if os.name != "nt":
            raise RuntimeError("自动滚动截图需要 Windows 10/11")
        self.api = user32()
        self.region = region
        self.layout = monitors()
        if not any(region.inside(m) for m in self.layout):
            raise RuntimeError("截图区域已不在当前显示器范围内，请重新框选")
        self.hwnd = self.root_at(*region.center)
        process = wintypes.DWORD()
        self.api.GetWindowThreadProcessId(self.hwnd, ctypes.byref(process))
        if not self.hwnd or process.value == os.getpid():
            raise RuntimeError("截图区域被本工具遮挡，请切换至微信或钉钉聊天窗口后重试")
        self.rect = self.window_rect()
        self.check()

    def root_at(self, x, y):
        window = self.api.WindowFromPoint(wintypes.POINT(x, y))
        return self.api.GetAncestor(window, 2) or window

    def window_rect(self):
        rect = wintypes.RECT()
        if not self.api.GetWindowRect(self.hwnd, ctypes.byref(rect)):
            raise RuntimeError("无法读取目标窗口位置")
        return rect.left, rect.top, rect.right, rect.bottom

    def check(self):
        if monitors() != self.layout:
            raise RuntimeError("显示器布局已改变，采集已停止，请重新框选")
        if not self.api.IsWindow(self.hwnd) or self.api.IsIconic(self.hwnd):
            raise RuntimeError("目标窗口已关闭或最小化，采集已停止")
        foreground = self.api.GetForegroundWindow()
        if (self.api.GetAncestor(foreground, 2) or foreground) != self.hwnd:
            raise RuntimeError("目标窗口失去焦点，采集已停止；已保存的原图仍保留")
        if self.window_rect() != self.rect:
            raise RuntimeError("目标窗口位置或大小已改变，请重新框选")
        r = self.region
        points = [r.center, (r.left + 2, r.top + 2),
                  (r.left + r.width - 3, r.top + 2),
                  (r.left + 2, r.top + r.height - 3),
                  (r.left + r.width - 3, r.top + r.height - 3)]
        if any(self.root_at(x, y) != self.hwnd for x, y in points):
            raise RuntimeError("截图区域被其他窗口遮挡，或超出聊天窗口，请重新框选")
