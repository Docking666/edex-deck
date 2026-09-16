#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Build standalone binaries for eDEX-Deck.

    python tools/build.py               # single-file binary for this platform
    python tools/build.py --portable    # also produce a portable zip
    python tools/build.py --onedir      # folder build instead of single file

Outputs to dist/.

Design notes
------------
* `--onefile` gives one double-clickable binary, which is what "one-click"
  actually means to an end user. Cost: ~1s of self-extraction on launch.
* `--onedir` starts instantly but is a folder, so it only makes sense shipped
  as a zip (`--portable`).
* `edex-deck.json` is deliberately NOT bundled — users need to edit it. The
  binary looks for it next to itself (see `app_dir()` in inject.py).
"""

import argparse
import os
import shutil
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "src")
DIST = os.path.join(ROOT, "dist")
WORK = os.path.join(ROOT, "build")

APP = "edex-deck"
ENTRY = os.path.join(SRC, "inject.py")


def run(cmd):
    print("$", " ".join(cmd), flush=True)
    r = subprocess.run(cmd)
    if r.returncode != 0:
        raise SystemExit("command failed with code %d" % r.returncode)


def build(onefile=True):
    os.makedirs(DIST, exist_ok=True)
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--name", APP,
        "--paths", SRC,
        "--distpath", DIST,
        "--workpath", WORK,
        "--specpath", WORK,
        # the layout kit is a runtime data blob read via import; keep it simple
        "--hidden-import", "layout_kit",
        "--hidden-import", "screenshot",
    ]
    if onefile:
        cmd.append("--onefile")
    else:
        cmd.append("--onedir")

    icon = os.path.join(ROOT, "assets", "logo.ico")
    if os.path.exists(icon):
        cmd += ["--icon", icon]

    cmd.append(ENTRY)
    run(cmd)


def make_portable():
    """Zip the single-file binary together with config, examples and licence.

    Deliberately does NOT reuse/clean a previous staging folder — some
    environments intercept deletes (shipping them to the recycle bin), which
    turns a rebuild into a hard failure. A fresh timestamped folder costs a few
    hundred KB under build/ and never blocks the build.
    """
    binary = os.path.join(DIST, APP + (".exe" if os.name == "nt" else ""))
    if not os.path.exists(binary):
        print("[portable] skipped: %s not found (build the binary first)" % binary)
        return None

    import time

    stage = os.path.join(WORK, "portable-%d" % int(time.time()), APP)
    os.makedirs(stage, exist_ok=True)

    shutil.copy2(binary, stage)
    for name in ("edex-deck.json", "README.md", "LICENSE"):
        src = os.path.join(ROOT, name)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(stage, name))

    ex_src = os.path.join(ROOT, "examples")
    if os.path.isdir(ex_src):
        shutil.copytree(ex_src, os.path.join(stage, "examples"))

    with open(os.path.join(stage, "README.txt"), "w", encoding="utf-8") as f:
        f.write(
            "eDEX-Deck - portable build\n"
            "==========================\n\n"
            "Double-click %s%s to launch eDEX with the layout dock injected.\n\n"
            "Requirements: eDEX-UI 2.2.x installed. Nothing else - Python is bundled.\n\n"
            "Edit edex-deck.json to add or change embed targets (profiles), then run:\n"
            "    %s%s --profile <name>\n"
            % (APP, ".exe" if os.name == "nt" else "",
               APP, ".exe" if os.name == "nt" else "")
        )

    zip_path = os.path.join(DIST, "%s-portable-%s.zip" % (APP, sys.platform))
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for base, _dirs, files in os.walk(stage):
            for fn in files:
                full = os.path.join(base, fn)
                z.write(full, os.path.relpath(full, os.path.dirname(stage)))
    print("[portable]", zip_path, os.path.getsize(zip_path), "bytes")
    return zip_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--portable", action="store_true",
                    help="also produce a portable zip (binary + config + examples)")
    args = ap.parse_args()

    if not os.path.exists(ENTRY):
        raise SystemExit("entry point not found: " + ENTRY)

    # single-file binary — the actual "double-click" artefact
    build(onefile=True)
    binary = os.path.join(DIST, APP + (".exe" if os.name == "nt" else ""))
    if os.path.exists(binary):
        print("[build] single-file:", binary, os.path.getsize(binary), "bytes")

    if args.portable:
        make_portable()
    return 0


if __name__ == "__main__":
    sys.exit(main())
