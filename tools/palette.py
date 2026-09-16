#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""零依赖 PNG 配色提取（纯标准库，只用 zlib 解压 + 手写反滤波）。"""

import collections
import struct
import sys
import zlib


def read_png(path):
    data = open(path, "rb").read()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a png")
    pos = 8
    idat = b""
    w = h = bitdepth = colortype = interlace = None
    while pos < len(data):
        ln = struct.unpack(">I", data[pos:pos + 4])[0]
        typ = data[pos + 4:pos + 8]
        chunk = data[pos + 8:pos + 8 + ln]
        pos += 12 + ln
        if typ == b"IHDR":
            w, h, bitdepth, colortype, _c, _f, interlace = struct.unpack(">IIBBBBB", chunk)
        elif typ == b"IDAT":
            idat += chunk
        elif typ == b"IEND":
            break
    if bitdepth != 8:
        raise ValueError("only 8-bit png supported, got %s" % bitdepth)
    if interlace != 0:
        raise ValueError("interlaced png not supported")
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[colortype]
    raw = zlib.decompress(idat)
    stride = w * channels
    out = bytearray(h * stride)
    prev = bytearray(stride)
    p = 0
    for y in range(h):
        f = raw[p]
        p += 1
        line = bytearray(raw[p:p + stride])
        p += stride
        if f == 1:
            for i in range(channels, stride):
                line[i] = (line[i] + line[i - channels]) & 255
        elif f == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 255
        elif f == 3:
            for i in range(stride):
                a = line[i - channels] if i >= channels else 0
                line[i] = (line[i] + ((a + prev[i]) >> 1)) & 255
        elif f == 4:
            for i in range(stride):
                a = line[i - channels] if i >= channels else 0
                b = prev[i]
                c = prev[i - channels] if i >= channels else 0
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 255
        out[y * stride:(y + 1) * stride] = line
        prev = line
    return w, h, channels, bytes(out)


def hexof(px, i, ch):
    if ch == 1:
        v = px[i]
        return "#%02X%02X%02X" % (v, v, v)
    o = i * ch
    return "#%02X%02X%02X" % (px[o], px[o + 1], px[o + 2])


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "shot_view.png"
    w, h, ch, px = read_png(path)
    lines = ["file: %s  %dx%d  channels=%d" % (path, w, h, ch)]

    counter = collections.Counter()
    step = 3
    for y in range(0, h, step):
        for x in range(0, w, step):
            counter[hexof(px, y * w + x, ch)] += 1

    lines.append("--- top 32 colors ---")
    total = sum(counter.values())
    for c, n in counter.most_common(32):
        lines.append("%s   %6d   %5.2f%%" % (c, n, n * 100.0 / total))

    lines.append("--- samples ---")
    pts = [
        ("center-bg", w // 2, int(h * 0.80)),
        ("topbar-bg", int(w * 0.78), 22),
        ("sidebar-bg", int(w * 0.06), int(h * 0.75)),
        ("sidebar-item", int(w * 0.06), int(h * 0.65)),
        ("title-text", int(w * 0.48), 24),
        ("avatar", 30, h - 16),
        ("search-box", int(w * 0.15), 28),
    ]
    for name, x, y in pts:
        x = max(0, min(x, w - 1))
        y = max(0, min(y, h - 1))
        lines.append("%-14s (%4d,%4d) = %s" % (name, x, y, hexof(px, y * w + x, ch)))

    lines.append("--- brightest pixels (top 12) ---")
    bright = collections.Counter()
    for y in range(0, h, 2):
        for x in range(0, w, 2):
            o = (y * w + x) * ch
            r, g, b = px[o], px[o + 1], px[o + 2]
            lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
            if lum > 150:
                bright["#%02X%02X%02X" % (r, g, b)] += 1
    for c, n in bright.most_common(12):
        lines.append("%s   %6d" % (c, n))

    txt = "\n".join(lines)
    out = path + ".palette.txt"
    with open(out, "w", encoding="utf-8") as f:
        f.write("\ufeff" + txt)
    print(txt)
    print("\nwritten:", out)


if __name__ == "__main__":
    main()
