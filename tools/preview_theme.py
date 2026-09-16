#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
临时切换 eDEX 主题 -> 跑注入流程截图 -> 自动还原 settings.json。

⚠️ settings.json 不是 UTF-8（含 GBK 编码的网卡名 iface）。
   所以全程按二进制处理，只正则替换 theme 字段，绝不做 JSON 解析重写 ——
   否则会把那个字段转义成乱码。

用法：
  python preview_theme.py deck-teal
"""

import os
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SETTINGS = os.path.join(os.environ.get("APPDATA", ""), "eDEX-UI", "settings.json")
BAK = SETTINGS + ".deck-teal-bak"
INJECT = os.path.join(HERE, "inject_webui.py")
SHOT = os.path.join(HERE, "shot.png")
VIEWSHOT = os.path.join(HERE, "shot_view.png")


def main():
    theme = sys.argv[1] if len(sys.argv) > 1 else "deck-teal"

    if not os.path.exists(SETTINGS):
        print("[preview] settings.json not found:", SETTINGS)
        return 1

    # 1) 存档上一轮截图，便于对比
    stamp = time.strftime("%H%M%S")
    for src, tag in ((SHOT, "full"), (VIEWSHOT, "view")):
        if os.path.exists(src):
            dst = os.path.join(HERE, "prev_%s_%s.png" % (tag, stamp))
            shutil.copy2(src, dst)
            print("[preview] archived:", dst)

    # 2) 备份 settings.json（二进制）
    shutil.copy2(SETTINGS, BAK)
    raw = open(SETTINGS, "rb").read()
    m = re.search(rb'"theme"\s*:\s*"([^"]*)"', raw)
    print("[preview] current theme:", m.group(1).decode("utf-8", "replace") if m else "?")

    try:
        new = re.sub(
            rb'"theme"\s*:\s*"[^"]*"',
            b'"theme": "' + theme.encode("utf-8") + b'"',
            raw,
            count=1,
        )
        if new == raw:
            print("[preview] WARNING: theme field not replaced (regex miss)")
        open(SETTINGS, "wb").write(new)
        print("[preview] switched to:", theme)

        # 3) 跑完整注入流程（起 serve -> 起 eDEX -> 注入 -> 截图 -> 收尾）
        r = subprocess.run(
            [sys.executable, INJECT],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        print("[preview] inject exit:", r.returncode)
        if r.stdout:
            tail = r.stdout[-2500:]
            print("--- inject stdout (tail) ---")
            print(tail)
    finally:
        try:
            shutil.copy2(BAK, SETTINGS)
            os.remove(BAK)
            print("[preview] settings.json restored, backup removed")
        except Exception as e:
            print("[preview] !! RESTORE FAILED:", e, "-> backup kept at", BAK)

    return 0


if __name__ == "__main__":
    sys.exit(main())
