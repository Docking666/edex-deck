#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
永久应用 eDEX 主题（不像 preview_theme.py 那样还原）。

⚠️ settings.json 不是 UTF-8（iface 字段是 GBK 编码的网卡名）。
   所以全程按二进制处理，只正则替换 theme 字段，绝不做 JSON 解析重写 ——
   否则那个字段会被转义成乱码。

用法：
  python apply_theme.py deck-teal
  python apply_theme.py matrix      # 切回去
"""

import os
import re
import shutil
import sys
import time

SETTINGS = os.path.join(os.environ.get("APPDATA", ""), "eDEX-UI", "settings.json")


def main():
    theme = sys.argv[1] if len(sys.argv) > 1 else "deck-teal"

    if not os.path.exists(SETTINGS):
        print("[apply] settings.json not found:", SETTINGS)
        return 1

    raw = open(SETTINGS, "rb").read()
    m = re.search(rb'"theme"\s*:\s*"([^"]*)"', raw)
    cur = m.group(1).decode("utf-8", "replace") if m else "?"
    print("[apply] current theme:", cur)

    if cur == theme:
        print("[apply] already on", theme, "- nothing to do")
        return 0

    bak = SETTINGS + ".bak-" + time.strftime("%Y%m%d-%H%M%S")
    shutil.copy2(SETTINGS, bak)
    print("[apply] backup ->", bak)

    new = re.sub(
        rb'"theme"\s*:\s*"[^"]*"',
        b'"theme": "' + theme.encode("utf-8") + b'"',
        raw,
        count=1,
    )
    if new == raw:
        print("[apply] ERROR: theme field not replaced (regex miss)")
        return 2

    open(SETTINGS, "wb").write(new)
    print("[apply] switched to:", theme)
    return 0


if __name__ == "__main__":
    sys.exit(main())
