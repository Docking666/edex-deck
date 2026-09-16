#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把若干 PNG 打包成一个多尺寸 .ico。

Vista 以后的 Windows 支持 ICO 里内嵌 PNG，所以不需要重新编码 ——
直接读每个 PNG 的 IHDR 拿尺寸，拼目录项即可。

用法：
  python png2ico.py out.ico 16.png 32.png 48.png ...
"""

import os
import struct
import sys


def png_size(path):
    with open(path, "rb") as f:
        head = f.read(24)
    if head[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a png: " + path)
    w, h = struct.unpack(">II", head[16:24])
    return w, h


def build_ico(paths, out_path):
    entries = []
    blobs = []
    offset = 6 + 16 * len(paths)
    for p in paths:
        w, h = png_size(p)
        data = open(p, "rb").read()
        entries.append((w, h, len(data), offset))
        blobs.append(data)
        offset += len(data)

    with open(out_path, "wb") as f:
        f.write(struct.pack("<HHH", 0, 1, len(paths)))
        for (w, h, size, off) in entries:
            # 256 在 ICO 目录里记作 0
            f.write(struct.pack(
                "<BBBBHHII",
                w if w < 256 else 0,
                h if h < 256 else 0,
                0, 0, 1, 32, size, off,
            ))
        for b in blobs:
            f.write(b)
    return out_path


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    out = os.path.abspath(sys.argv[1])
    ins = [os.path.abspath(p) for p in sys.argv[2:]]
    for p in ins:
        if not os.path.exists(p):
            print("missing:", p)
            return 1
    build_ico(ins, out)
    print("ok ->", out, os.path.getsize(out), "bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
