"""
Phase D - observe-everything (the device watching ITSELF, locally).

Slices:
  D1  active window (title + process) and clipboard text       - stdlib ctypes
  D2  focused-control text (best-effort, classic Win32 apps)    - stdlib ctypes
  D3  screen OCR                                                - needs an OCR backend

Windows-only via ctypes; every function guards os.name and returns None elsewhere,
so importing/calling on mac/Linux is safe (those backends come later). Nothing here
captures on its own - the service's observe loop calls these, gated by the consent
ledger + global pause, and observation is OFF until the user turns it on.
"""
from __future__ import annotations
import os

_WIN = os.name == "nt"
_configured = False


def _cfg():
    global _configured
    if _configured or not _WIN:
        return
    import ctypes
    from ctypes import wintypes
    u, k = ctypes.windll.user32, ctypes.windll.kernel32
    u.GetForegroundWindow.restype = wintypes.HWND
    u.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    u.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    u.GetWindowThreadProcessId.restype = wintypes.DWORD
    k.OpenProcess.restype = wintypes.HANDLE
    k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                             wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    k.GlobalLock.restype = ctypes.c_void_p
    k.GlobalLock.argtypes = [wintypes.HGLOBAL]
    k.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    u.GetClipboardData.restype = wintypes.HANDLE
    u.GetClipboardData.argtypes = [wintypes.UINT]
    u.OpenClipboard.argtypes = [wintypes.HWND]
    u.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
    u.SendMessageW.restype = wintypes.LPARAM
    u.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    _configured = True


# ---- D1: active window -------------------------------------------------------
def _process_name(pid):
    import ctypes
    from ctypes import wintypes
    k = ctypes.windll.kernel32
    h = k.OpenProcess(0x1000, False, pid)        # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return None
    try:
        buf = ctypes.create_unicode_buffer(512)
        size = wintypes.DWORD(512)
        if k.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value)
    finally:
        k.CloseHandle(h)
    return None


def active_window():
    if not _WIN:
        return None
    _cfg()
    import ctypes
    from ctypes import wintypes
    u = ctypes.windll.user32
    hwnd = u.GetForegroundWindow()
    if not hwnd:
        return None
    n = u.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    u.GetWindowTextW(hwnd, buf, n + 1)
    pid = wintypes.DWORD()
    u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return {"title": buf.value, "process": _process_name(pid.value) or "", "pid": pid.value}


# ---- D1: clipboard -----------------------------------------------------------
def read_clipboard_text():
    if not _WIN:
        return None
    _cfg()
    import ctypes
    u, k = ctypes.windll.user32, ctypes.windll.kernel32
    if not u.OpenClipboard(0):
        return None
    try:
        if not u.IsClipboardFormatAvailable(13):   # CF_UNICODETEXT
            return None
        h = u.GetClipboardData(13)
        if not h:
            return None
        ptr = k.GlobalLock(h)
        if not ptr:
            return None
        try:
            return ctypes.c_wchar_p(ptr).value
        finally:
            k.GlobalUnlock(h)
    finally:
        u.CloseClipboard()


# ---- D2: focused-control text --------------------------------------------------
def _uia_focused_text(max_chars):
    """Full UI-Automation path: reads the focused element's text in modern apps
    (Chrome/Electron/UWP/Office). Optional dep `uiautomation`; returns None if
    unavailable so we fall back to the classic Win32 path."""
    try:
        import uiautomation as auto
    except Exception:
        return None
    try:
        ctrl = auto.GetFocusedControl()
        if ctrl is None:
            return None
        txt = ""
        try:
            txt = ctrl.GetValuePattern().Value or ""
        except Exception:
            pass
        if not txt:
            try:
                txt = ctrl.GetTextPattern().DocumentRange.GetText(max_chars) or ""
            except Exception:
                pass
        if not txt:
            txt = getattr(ctrl, "Name", "") or ""
        return (txt[:max_chars] or None)
    except Exception:
        return None


def focused_text(max_chars=4000):
    if not _WIN:
        return None
    uia = _uia_focused_text(max_chars)      # modern apps (optional dep)
    if uia:
        return uia
    _cfg()                                   # classic Win32 fallback (WM_GETTEXT)
    import ctypes
    from ctypes import wintypes

    class GTI(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD),
                    ("hwndActive", wintypes.HWND), ("hwndFocus", wintypes.HWND),
                    ("hwndCapture", wintypes.HWND), ("hwndMenuOwner", wintypes.HWND),
                    ("hwndMoveSize", wintypes.HWND), ("hwndCaret", wintypes.HWND),
                    ("rcCaret", wintypes.RECT)]
    u = ctypes.windll.user32
    hwnd = u.GetForegroundWindow()
    if not hwnd:
        return None
    tid = u.GetWindowThreadProcessId(hwnd, None)
    gti = GTI()
    gti.cbSize = ctypes.sizeof(gti)
    focus = hwnd
    if u.GetGUIThreadInfo(tid, ctypes.byref(gti)) and gti.hwndFocus:
        focus = gti.hwndFocus
    n = u.SendMessageW(focus, 0x000E, 0, 0)        # WM_GETTEXTLENGTH
    if not n:
        return None
    n = min(n, max_chars)
    buf = ctypes.create_unicode_buffer(n + 1)
    u.SendMessageW(focus, 0x000D, n + 1, ctypes.addressof(buf))   # WM_GETTEXT
    return buf.value or None


# ---- D3: screen OCR (needs a backend; honest degrade) ------------------------
_ocr_engine = None


def ocr_available():
    try:
        import rapidocr_onnxruntime  # noqa: F401  (on-device, no external binary)
        return "rapidocr"
    except Exception:
        pass
    try:
        import pytesseract  # noqa: F401
        return "tesseract"
    except Exception:
        return None


def ocr_image_path(path: str) -> str:
    """OCR an image file -> recognized text. Uses rapidocr (else tesseract)."""
    backend = ocr_available()
    if backend == "rapidocr":
        global _ocr_engine
        if _ocr_engine is None:
            from rapidocr_onnxruntime import RapidOCR
            _ocr_engine = RapidOCR()
        result, _elapse = _ocr_engine(path)
        return "\n".join(item[1] for item in (result or []))
    if backend == "tesseract":
        from PIL import Image
        import pytesseract
        return pytesseract.image_to_string(Image.open(path))
    return ""


def capture_screen_text():
    backend = ocr_available()
    if not backend:
        return {"error": "no OCR backend installed",
                "hint": "pip install rapidocr-onnxruntime  (on-device, no external binary)"}
    try:
        import os
        import tempfile
        from PIL import ImageGrab
        img = ImageGrab.grab()
        tmp = os.path.join(tempfile.gettempdir(), "_aci_screen.png")
        img.save(tmp)
        text = ocr_image_path(tmp)
        try:
            os.remove(tmp)
        except OSError:
            pass
        return {"backend": backend, "chars": len(text), "text": text}
    except Exception as e:
        return {"error": str(e), "backend": backend}
