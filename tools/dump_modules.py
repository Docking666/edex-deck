#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 dom.json 里提取 eDEX 各模块的 id / class（用于做模块级开关）。"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "dom.json")

raw = json.load(open(path, encoding="utf-8"))
nodes = raw.get("nodes", raw if isinstance(raw, list) else [])
lines = ["win: %s" % raw.get("win"), "total nodes: %d" % len(nodes), ""]

groups = {}
for n in nodes:
    cls = str(n.get("cls", ""))
    nid = str(n.get("id", ""))
    key = None
    if cls.startswith("mod_column") or nid.startswith("mod_column"):
        key = "COLUMN"
    elif nid.startswith("mod_") or cls.startswith("mod_"):
        key = "MODULE"
    elif "globe" in nid.lower() or "globe" in cls.lower():
        key = "GLOBE"
    elif nid in ("main_shell", "filesystem", "keyboard", "boot_screen"):
        key = "SHELL"
    if key:
        groups.setdefault(key, []).append(n)

for key in ("COLUMN", "MODULE", "GLOBE", "SHELL"):
    lines.append("=== %s ===" % key)
    for n in groups.get(key, []):
        lines.append(
            "  d=%s tag=%-6s id=%-28s cls=%-30s %4d,%-4d %4dx%-4d"
            % (n.get("d"), n.get("tag"), n.get("id", ""), str(n.get("cls", ""))[:30],
               n.get("x", 0), n.get("y", 0), n.get("w", 0), n.get("h", 0))
        )
    lines.append("")

txt = "\n".join(lines)
out = os.path.join(HERE, "modules.txt")
open(out, "w", encoding="utf-8").write("\ufeff" + txt)
print(txt[:3000])
print("written:", out)
