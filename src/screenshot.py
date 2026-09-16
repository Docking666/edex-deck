#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cross-platform screen capture with no third-party dependencies.

Why this exists: CDP's `Page.captureScreenshot` only captures the renderer.
Native child views (like the BrowserView used to embed a Web UI) live in a
separate compositing layer, so documenting the *whole* window needs a real
screen grab.

    Windows  ctypes + GDI (BitBlt), PNG encoded with zlib
    macOS    screencapture
    Linux    ImageMagick `import`, or gnome-screenshot

Usage:
    python src/screenshot.py out.png
"""

import os
import struct
import subprocess
import sys
import zlib


# ------------------------------------------------------------------ png

def png_encode(width, height, rows):
    """Encode 8-bit RGB scanlines (already filtered with filter type 0)."""
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

def _win_capture():
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

    user32.SetProcessDPIAware()
    w = user32.GetSystemMetrics(0)
    h = user32.GetSystemMetrics(1)

    hdc = user32.GetDC(0)
    mem = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    gdi32.SelectObject(mem, bmp)
    SRCCOPY = 0x00CC0020
    gdi32.BitBlt(mem, 0, 0, w, h, hdc, 0, 0, SRCCOPY)

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", wintypes.DWORD),
            ("biWidth", wintypes.LONG),
            ("biHeight", wintypes.LONG),
            ("biPlanes", wintypes.WORD),
            ("biBitCount", wintypes.WORD),
            ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD),
            ("biXPelsPerMeter", wintypes.LONG),
            ("biYPelsPerMeter", wintypes.LONG),
            ("biClrUsed", wintypes.DWORD),
            ("biClrImportant", wintypes.DWORD),
        ]

    bi = BITMAPINFOHEADER()
    bi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bi.biWidth = w
    bi.biHeight = -h          # negative => top-down rows
    bi.biPlanes = 1
    bi.biBitCount = 32
    bi.biCompression = 0      # BI_RGB

    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(bi), 0)

    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mem)
    user32.ReleaseDC(0, hdc)

    data = buf.raw
    rows = []
    for y in range(h):
        off = y * w * 4
        line = bytearray(w * 3)
        line[0::3] = data[off:off + w * 4:4]          # B -> R
        line[1::3] = data[off + 1:off + w * 4:4]      # G -> G
        line[2::3] = data[off + 2:off + w * 4:4]      # R -> B
        rows.append(bytes(line))
    return w, h, rows


# ------------------------------------------------------------------ api

def capture(path):
    """Grab the whole screen into `path` (PNG). Returns True on success."""
    path = os.path.abspath(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)

    if sys.platform == "win32":
        w, h, rows = _win_capture()
        with open(path, "wb") as f:
            f.write(png_encode(w, h, rows))
        return True

    if sys.platform == "darwin":
        r = subprocess.run(["screencapture", "-x", path], capture_output=True)
        return r.returncode == 0 and os.path.exists(path)

    for cmd in (
        ["import", "-window", "root", path],
        ["gnome-screenshot", "-f", path],
        ["grim", path],
    ):
        try:
            r = subprocess.run(cmd, capture_output=True)
            if r.returncode == 0 and os.path.exists(path):
                return True
        except FileNotFoundError:
            continue
    return False


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "screenshot.png"
    ok = capture(out)
    print("ok ->" if ok else "failed ->", out)
    sys.exit(0 if ok else 1)
