#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cross-platform screen / window capture with no third-party dependencies.

Why this exists: CDP's `Page.captureScreenshot` only captures the renderer, and
spinning up a whole browser just to save a PNG is expensive. For "take a picture
of the result" tasks this needs none of that — it is pure stdlib + ctypes and
costs a few milliseconds.

    Windows  ctypes + GDI (BitBlt / PrintWindow), PNG encoded with zlib
    macOS    screencapture
    Linux    ImageMagick `import`, gnome-screenshot, or grim

What it is NOT: a replacement for browser automation. No DOM access, no
element targeting, no interaction. Use it for result snapshots and visual
archiving, not for assertions.

Usage:
    python screenshot.py out.png                    # whole virtual desktop
    python screenshot.py out.png --monitor 1        # second monitor
    python screenshot.py out.png --region 100,80,640,480
    python screenshot.py out.png --window 0x00123ABC
    python screenshot.py out.png --list
"""

import argparse
import os
import struct
import subprocess
import sys
import zlib


# ------------------------------------------------------------------ png

def png_encode(width, height, rows):
    """Encode 8-bit RGB scanlines (each already prefixed with filter type 0)."""
    raw = b"".join(b"\x00" + r for r in rows)
    comp = zlib.compress(raw, 6)

    def chunk(tag, data):
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(
            ">I", zlib.crc32(body) & 0xFFFFFFFF
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", comp)
        + chunk(b"IEND", b"")
    )


# ------------------------------------------------------------------ windows

class _Win:
    """Lazy ctypes bindings so the module imports fine on other platforms."""

    def __init__(self):
        import ctypes
        from ctypes import wintypes

        self.ctypes = ctypes
        self.wintypes = wintypes
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
        self.user32.SetProcessDPIAware()
        self.SRCCOPY = 0x00CC0020
        self.PW_RENDERFULLCONTENT = 2

    # ---- geometry

    def virtual_desktop(self):
        u = self.user32
        x = u.GetSystemMetrics(76)   # SM_XVIRTUALSCREEN
        y = u.GetSystemMetrics(77)   # SM_YVIRTUALSCREEN
        w = u.GetSystemMetrics(78)   # SM_CXVIRTUALSCREEN
        h = u.GetSystemMetrics(79)   # SM_CYVIRTUALSCREEN
        return (x, y, w, h)

    def monitors(self):
        """[(x, y, w, h), ...] in virtual-desktop coordinates."""
        ctypes = self.ctypes
        from ctypes import wintypes

        found = []

        class RECT(ctypes.Structure):
            _fields_ = [
                ("left", wintypes.LONG), ("top", wintypes.LONG),
                ("right", wintypes.LONG), ("bottom", wintypes.LONG),
            ]

        MONITORENUMPROC = ctypes.WINFUNCTYPE(
            wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC,
            ctypes.POINTER(RECT), wintypes.LPARAM,
        )

        def cb(_hmon, _hdc, lprc, _data):
            r = lprc.contents
            found.append((r.left, r.top, r.right - r.left, r.bottom - r.top))
            return True

        self.user32.EnumDisplayMonitors(0, None, MONITORENUMPROC(cb), 0)
        return found

    def window_rect(self, hwnd):
        from ctypes import wintypes

        r = wintypes.RECT()
        if not self.user32.GetWindowRect(hwnd, self.ctypes.byref(r)):
            raise RuntimeError("GetWindowRect failed for hwnd %s" % hwnd)
        return (r.left, r.top, r.right - r.left, r.bottom - r.top)

    # ---- pixels

    def _dib_to_rows(self, mem, bmp, w, h):
        ctypes = self.ctypes
        from ctypes import wintypes

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [
                ("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD),
            ]

        bi = BITMAPINFOHEADER()
        bi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bi.biWidth = w
        bi.biHeight = -h          # negative => top-down
        bi.biPlanes = 1
        bi.biBitCount = 32
        bi.biCompression = 0

        buf = ctypes.create_string_buffer(w * h * 4)
        self.gdi32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(bi), 0)
        data = buf.raw

        rows = []
        for y in range(h):
            off = y * w * 4
            line = bytearray(w * 3)
            line[0::3] = data[off:off + w * 4:4]          # B -> R
            line[1::3] = data[off + 1:off + w * 4:4]      # G -> G
            line[2::3] = data[off + 2:off + w * 4:4]      # R -> B
            rows.append(bytes(line))
        return rows

    def grab_screen(self, region):
        ctypes = self.ctypes
        x, y, w, h = region
        hdc = self.user32.GetDC(0)
        mem = self.gdi32.CreateCompatibleDC(hdc)
        bmp = self.gdi32.CreateCompatibleBitmap(hdc, w, h)
        self.gdi32.SelectObject(mem, bmp)
        self.gdi32.BitBlt(mem, 0, 0, w, h, hdc, x, y, self.SRCCOPY)
        rows = self._dib_to_rows(mem, bmp, w, h)
        self.gdi32.DeleteObject(bmp)
        self.gdi32.DeleteDC(mem)
        self.user32.ReleaseDC(0, hdc)
        return rows

    def grab_window(self, hwnd):
        """PrintWindow renders the window even when it is occluded."""
        ctypes = self.ctypes
        _, _, w, h = self.window_rect(hwnd)
        wdc = self.user32.GetWindowDC(hwnd)
        mem = self.gdi32.CreateCompatibleDC(wdc)
        bmp = self.gdi32.CreateCompatibleBitmap(wdc, w, h)
        self.gdi32.SelectObject(mem, bmp)
        ok = self.user32.PrintWindow(hwnd, mem, self.PW_RENDERFULLCONTENT)
        if not ok:
            self.gdi32.BitBlt(mem, 0, 0, w, h, wdc, 0, 0, self.SRCCOPY)
        rows = self._dib_to_rows(mem, bmp, w, h)
        self.gdi32.DeleteObject(bmp)
        self.gdi32.DeleteDC(mem)
        self.user32.ReleaseWindowDC(hwnd)
        return rows


_win = None


def _win_api():
    global _win
    if _win is None:
        _win = _Win()
    return _win


def windows_list():
    """[(index, x, y, w, h), ...] — usable for --list."""
    w = _win_api()
    return list(enumerate(w.monitors()))


# ------------------------------------------------------------------ api

def capture(path, monitor=None, region=None, hwnd=None):
    """
    Grab a picture into `path` (PNG). Returns True on success.

    monitor  int   index into the monitor list (0 = primary as reported by the OS)
    region   tuple (x, y, w, h)
    hwnd     int   window handle (Windows only); works even if occluded

    Precedence: hwnd > region > monitor > whole virtual desktop.
    """
    path = os.path.abspath(path)
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    # ---- macOS
    if sys.platform == "darwin":
        cmd = ["screencapture", "-x"]
        if region:
            x, y, w, h = region
            cmd += ["-R", "%d,%d,%d,%d" % (x, y, w, h)]
        cmd.append(path)
        r = subprocess.run(cmd, capture_output=True)
        return r.returncode == 0 and os.path.exists(path)

    # ---- Linux
    if sys.platform != "win32":
        for base in (["import", "-window", "root"], ["gnome-screenshot", "-f"], ["grim"]):
            cmd = list(base)
            if region and base[0] == "import":
                x, y, w, h = region
                cmd += ["-crop", "%dx%d+%d+%d" % (w, h, x, y)]
            cmd.append(path)
            try:
                if subprocess.run(cmd, capture_output=True).returncode == 0 and os.path.exists(path):
                    return True
            except FileNotFoundError:
                continue
        return False

    # ---- Windows
    api = _win_api()
    if hwnd:
        rows = api.grab_window(hwnd)
        w, h = _win_api().window_rect(hwnd)[2:]
    else:
        if region:
            box = region
        elif monitor is not None:
            mons = api.monitors()
            if not mons:
                raise RuntimeError("no monitors reported")
            box = mons[monitor % len(mons)]
        else:
            box = api.virtual_desktop()
        rows = api.grab_screen(box)
        w, h = box[2], box[3]

    with open(path, "wb") as f:
        f.write(png_encode(w, h, rows))
    return True


def parse_region(text):
    parts = [p.strip() for p in text.split(",")]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("region must be x,y,w,h")
    return tuple(int(p) for p in parts)


def main():
    ap = argparse.ArgumentParser(description="dependency-free screen capture")
    ap.add_argument("path", nargs="?", default="screenshot.png")
    ap.add_argument("--monitor", type=int, help="monitor index")
    ap.add_argument("--region", type=parse_region, help="x,y,w,h")
    ap.add_argument("--window", help="window handle, e.g. 0x00123ABC")
    ap.add_argument("--list", action="store_true", help="list monitors and exit")
    args = ap.parse_args()

    if args.list:
        if sys.platform != "win32":
            print("monitor listing is only implemented on Windows yet")
            return 0
        for i, (x, y, w, h) in windows_list():
            print("monitor %d: x=%d y=%d %dx%d" % (i, x, y, w, h))
        return 0

    hwnd = int(args.window, 0) if args.window else None
    ok = capture(args.path, monitor=args.monitor, region=args.region, hwnd=hwnd)
    print(("ok -> " if ok else "failed -> ") + args.path)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
