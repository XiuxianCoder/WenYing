from __future__ import annotations
import ctypes
import sys


_instance_mutex = None


def _ensure_single_instance() -> None:
    """Keep one WenYing process per Windows login session."""
    global _instance_mutex
    if sys.platform != "win32":
        return
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = (ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p)
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    handle = kernel32.CreateMutexW(None, False, "Local\\WenYing.Desktop.Singleton")
    if not handle:
        return
    if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        ctypes.windll.kernel32.CloseHandle(handle)
        hwnd = ctypes.windll.user32.FindWindowW(None, "文映 WenYing · 公众号排版")
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            ctypes.windll.user32.BringWindowToTop(hwnd)
            ctypes.windll.user32.SetForegroundWindow(hwnd)
        raise SystemExit(0)
    _instance_mutex = handle


_ensure_single_instance()

try:
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("WenYing.Desktop.2")
except Exception:
    pass
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass
from wenying.app_window import WenYingApp, run
__all__ = ["WenYingApp", "run"]
if __name__ == "__main__":
    run()

