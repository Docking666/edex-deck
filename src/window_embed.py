#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Attach a native OS window into the eDEX window (Windows only).

Why this exists: a BrowserView only swallows HTTP content, so it can never host
a native application. To put Blender, a file manager, or any other program
inside the eDEX frame you have to reparent the real window handle — on Windows
that means user32.SetParent, which genuinely changes the window's owner.

Caveats, and they matter:
  * Windows-only. X11 has XReparentWindow but Wayland deliberately does not
    allow it, and macOS does not permit cross-process window embedding at all.
  * Reparenting changes the child's style (drops its caption/frame) and moves it
    into the parent's coordinate space. Some applications repaint badly or
    misbehave; detach restores the original style.
  * DPI awareness: if the two windows live on monitors with different scaling,
    the child can land at the wrong size. The parent should declare
    per-monitor DPI awareness.

Usage:
    python window_embed.py list
    python window_embed.py attach --window <hwnd> [--parent <hwnd>] [--rect x,y,w,h]
    python window_embed.py detach --window <hwnd>
"""

import argparse
import ctypes
import sys
from ctypes import wintypes

IS_WIN = sys.platform == "win32"

GWL_STYLE = -16
GWL_EXSTYLE = -20

WS_CHILD = 0x40000000
WS_POPUP = 0x80000000
WS_CAPTION = 0x00C00000
WS_THICKFRAME = 0x00040000
WS_MINIMIZEBOX = 0x00020000
WS_MAXIMIZEBOX = 0x00010000
WS_SYSMENU = 0x00080000
WS_EX_APPWINDOW = 0x00040000
WS_EX_TOOLWINDOW = 0x00000080

WM_NULL = 0x0000


def as_int(h):
    """Convert a window handle (possibly a ctypes HWND) to a plain int."""
    if isinstance(h, int):
        return h
    v = getattr(h, "value", None)
    if v is not None:
        try:
            return int(v)
        except Exception:
            return 0
    try:
        return int(h)
    except Exception:
        return 0

# Reparenting any of these would wreck the desktop rather than decorate it.
SKIP_CLASSES = {
    "Progman",                        # 桌面
    "WorkerW",
    "Shell_TrayWnd",                  # 任务栏
    "Shell_SecondaryTrayWnd",
    "Shell_SecondaryTrayWndHelper",
    "Windows.UI.Core.CoreWindow",     # UWP 系统组件 / 输入法
    "CEF-OSC-WIDGET",                 # 显卡 overlay 之类
    "Windows.UI.CompositionWindowBridge",
    "ApplicationFrameWindow",         # UWP 外壳，嵌进去只会得到空框
}


class Win32:
    def __init__(self):
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.u = self.user32

        self.u.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        self.u.GetWindowTextW.restype = ctypes.c_int
        self.u.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        self.u.GetWindowTextLengthW.restype = ctypes.c_int
        self.u.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        self.u.GetClassNameW.restype = ctypes.c_int
        self.u.EnumWindows.argtypes = [ctypes.c_void_p, wintypes.LPARAM]
        self.u.EnumWindows.restype = wintypes.BOOL
        self.u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        self.u.GetWindowThreadProcessId.restype = wintypes.DWORD
        self.u.SetParent.argtypes = [wintypes.HWND, wintypes.HWND]
        self.u.SetParent.restype = wintypes.HWND
        self.u.MoveWindow.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                      ctypes.c_int, ctypes.c_int, wintypes.BOOL]
        self.u.MoveWindow.restype = wintypes.BOOL
        self.u.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
        self.u.GetWindowLongW.restype = ctypes.c_long
        self.u.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
        self.u.SetWindowLongW.restype = ctypes.c_long

    # ---- queries

    def title(self, hwnd):
        n = self.u.GetWindowTextLengthW(hwnd)
        if n <= 0:
            return ""
        buf = ctypes.create_unicode_buffer(n + 1)
        self.u.GetWindowTextW(hwnd, buf, n + 1)
        return buf.value

    def cls(self, hwnd):
        buf = ctypes.create_unicode_buffer(256)
        self.u.GetClassNameW(hwnd, buf, 256)
        return buf.value

    def pid(self, hwnd):
        p = wintypes.DWORD()
        self.u.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
        return p.value

    def exe_of(self, pid):
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        h = self.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(1024)
            if self.kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                return buf.value
            return ""
        finally:
            self.kernel32.CloseHandle(h)

    def list_windows(self, skip_untitled=True, skip_self=False):
        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        out = []

        def cb(hwnd, _lp):
            if not self.u.IsWindowVisible(hwnd):
                return True
            t = self.title(hwnd)
            if skip_untitled and not t:
                return True
            # 跳过被别的窗口领养的（已经是子窗口）
            if self.u.GetParent(hwnd):
                return True
            if self.cls(hwnd) in SKIP_CLASSES:
                return True
            out.append(hwnd)
            return True

        self.u.EnumWindows(WNDENUMPROC(cb), 0)

        rows = []
        for hwnd in out:
            t = self.title(hwnd)
            if skip_self and t.startswith("eDEX-UI"):
                continue
            pid = self.pid(hwnd)
            rows.append({
                # 句柄是 ctypes 的 HWND，直接 json.dumps 会 TypeError ——
                # 必须落成普通 int，否则设置页拿到的会是空响应体
                "hwnd": as_int(hwnd),
                "title": t,
                "class": self.cls(hwnd),
                "pid": pid,
                "exe": self.exe_of(pid),
            })
        return rows

    def find(self, title_contains=None, class_name=None, exe_contains=None):
        for w in self.list_windows():
            if title_contains and title_contains.lower() not in (w["title"] or "").lower():
                continue
            if class_name and class_name != w["class"]:
                continue
            if exe_contains and exe_contains.lower() not in (w["exe"] or "").lower():
                continue
            return w
        return None

    def find_by_exe(self, exe_fragment, exclude_hwnd=None):
        """Locate a window by its executable path.

        Preferred over title matching for the host window: eDEX is borderless
        and its title can be empty, but the exe path is always stable.
        """
        frag = (exe_fragment or "").lower()
        for w in self.list_windows(skip_untitled=False):
            if exclude_hwnd and w["hwnd"] == exclude_hwnd:
                continue
            if frag in (w["exe"] or "").lower():
                return w
        return None

    # ---- embedding

    def attach(self, hwnd, parent_hwnd, x, y, w, h):
        """Reparent hwnd into parent_hwnd and position it. Returns the old style."""
        old_style = self.u.GetWindowLongW(hwnd, GWL_STYLE)
        style = old_style
        style |= WS_CHILD
        style &= ~WS_POPUP
        style &= ~WS_CAPTION
        style &= ~WS_THICKFRAME
        style &= ~WS_SYSMENU
        self.u.SetWindowLongW(hwnd, GWL_STYLE, style)

        ex = self.u.GetWindowLongW(hwnd, GWL_EXSTYLE)
        self.u.SetWindowLongW(hwnd, GWL_EXSTYLE, (ex & ~WS_EX_APPWINDOW) | WS_EX_TOOLWINDOW)

        if not self.u.SetParent(hwnd, parent_hwnd):
            return None
        self.u.MoveWindow(hwnd, int(x), int(y), int(w), int(h), True)
        return old_style

    def detach(self, hwnd, old_style=None):
        if old_style is not None:
            self.u.SetWindowLongW(hwnd, GWL_STYLE, old_style)
        self.u.SetParent(hwnd, 0)
        return True


_api = None


def api():
    global _api
    if _api is None:
        if not IS_WIN:
            raise RuntimeError("window embedding is only available on Windows")
        _api = Win32()
    return _api


def main():
    ap = argparse.ArgumentParser(description="attach a native window into eDEX")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="list candidate windows")

    a = sub.add_parser("attach")
    a.add_argument("--window", required=True, help="hwnd (hex like 0x00123ABC) or a title fragment")
    a.add_argument("--parent", help="parent hwnd; defaults to the eDEX window")
    a.add_argument("--rect", help="x,y,w,h inside the parent")

    d = sub.add_parser("detach")
    d.add_argument("--window", required=True)

    args = ap.parse_args()
    w32 = api()

    if args.cmd == "list":
        for w in w32.list_windows():
            print("0x%08X  %-40s %-28s %s" % (
                w["hwnd"], (w["title"] or "")[:40],
                (w["exe"] or "").split("\\")[-1][:28], w["class"]))
        return 0

    def resolve(spec):
        if spec.lower().startswith("0x"):
            return int(spec, 16)
        try:
            return int(spec)
        except ValueError:
            m = w32.find(title_contains=spec)
            return m["hwnd"] if m else None

    hwnd = resolve(args.window)
    if not hwnd:
        print("window not found:", args.window)
        return 1

    if args.cmd == "attach":
        parent = int(args.parent, 16) if args.parent else None
        if parent is None:
            m = w32.find_by_exe("eDEX-UI.exe")
            if not m:
                print("eDEX window not found — is it running?")
                return 1
            parent = m["hwnd"]
        rect = [int(v) for v in (args.rect.split(",") if args.rect else ["0", "0", "800", "600"])]
        old = w32.attach(hwnd, parent, *rect)
        if old is None:
            print("attach failed:", ctypes.get_last_error())
            return 1
        print("attached 0x%08X -> parent 0x%08X rect=%s (old style 0x%X)" % (hwnd, parent, rect, old))
        return 0

    if args.cmd == "detach":
        w32.detach(hwnd)
        print("detached 0x%08X" % hwnd)
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
