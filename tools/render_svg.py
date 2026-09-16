#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SVG -> PNG 渲染器（headless Chrome + CDP）。

用途：把 assets/ 下的 logo 渲染成 README 用的位图。
不依赖 cairosvg / rsvg 等原生库，只用本机已有的 Chrome。

用法：
  python render_svg.py assets/logo.svg assets/logo.png 512
"""

import base64
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request

import websocket

HERE = os.path.dirname(os.path.abspath(__file__))

CHROME_CANDIDATES = [
    os.path.join(
        os.path.expanduser("~"),
        ".agent-browser", "browsers", "chrome-152.0.7977.64", "chrome.exe",
    ),
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]


def find_chrome():
    for c in CHROME_CANDIDATES:
        if os.path.exists(c):
            return c
    raise RuntimeError("no chrome found; tried:\n  " + "\n  ".join(CHROME_CANDIDATES))


def port_open(port):
    import socket

    s = socket.socket()
    s.settimeout(0.6)
    try:
        s.connect(("127.0.0.1", port))
        return True
    except Exception:
        return False
    finally:
        s.close()


class CDP:
    def __init__(self, ws_url, timeout=30):
        self.ws = websocket.create_connection(ws_url, timeout=timeout, suppress_origin=True)
        self.seq = 0

    def send(self, method, params=None, timeout=30):
        self.seq += 1
        mid = self.seq
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        deadline = time.time() + timeout
        while time.time() < deadline:
            raw = self.ws.recv()
            if not raw:
                continue
            msg = json.loads(raw)
            if msg.get("id") == mid:
                return msg
        raise TimeoutError(method)

    def ev(self, expr, timeout=20):
        r = self.send(
            "Runtime.evaluate",
            {"expression": expr, "returnByValue": True, "awaitPromise": True},
            timeout=timeout,
        )
        res = r.get("result", {})
        if "exceptionDetails" in res:
            return "ERR: " + str(res["exceptionDetails"].get("text"))
        return res.get("result", {}).get("value")

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


def svg_ratio(svg_text):
    """从 viewBox 读宽高比；读不到就按正方形处理。"""
    import re

    m = re.search(
        r'viewBox\s*=\s*["\']\s*[-\d.]+\s+[-\d.]+\s+([\d.]+)\s+([\d.]+)', svg_text
    )
    if m:
        w, h = float(m.group(1)), float(m.group(2))
        if w > 0 and h > 0:
            return w, h
    return 512.0, 512.0


def wrap_html(svg_path, width):
    """把 SVG 包进零边距 HTML —— 裸 SVG 直接打开时 Chrome 会居中缩放，截图尺寸不可控。
    高度按 viewBox 比例算，否则横版 logo 会被拉成正方形。"""
    svg = open(svg_path, encoding="utf-8").read()
    vw, vh = svg_ratio(svg)
    height = int(round(width * vh / vw))
    svg = svg.replace(
        "<svg ",
        '<svg style="display:block;width:%dpx;height:%dpx" ' % (width, height),
        1,
    )
    html = (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        "<style>html,body{margin:0;padding:0;background:#000;overflow:hidden}</style>"
        "</head><body>" + svg + "</body></html>"
    )
    return height, html


def main():
    svg_path = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "assets/logo.svg")
    out_path = os.path.abspath(sys.argv[2] if len(sys.argv) > 2 else "assets/logo.png")
    size = int(sys.argv[3]) if len(sys.argv) > 3 else 512

    chrome = find_chrome()
    port = 9401
    tmp = tempfile.mkdtemp(prefix="render_svg_")
    html_path = os.path.join(tmp, "page.html")
    height, html = wrap_html(svg_path, size)
    open(html_path, "w", encoding="utf-8").write(html)

    args = [
        chrome, "--headless=new", "--disable-gpu", "--no-first-run",
        "--no-default-browser-check", "--hide-scrollbars",
        "--user-data-dir=" + os.path.join(tmp, "profile"),
        "--remote-debugging-port=%d" % port,
        "--window-size=%d,%d" % (size, height),
        "file:///" + html_path.replace("\\", "/"),
    ]
    proc = subprocess.Popen(
        args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )

    cdp = None
    try:
        for _ in range(40):
            if port_open(port):
                break
            time.sleep(0.5)

        tgt = None
        for _ in range(20):
            try:
                with urllib.request.urlopen("http://127.0.0.1:%d/json/list" % port, timeout=4) as r:
                    ts = json.load(r)
                tgt = next((t for t in ts if t.get("type") == "page" and "page.html" in str(t.get("url"))), None)
                if tgt:
                    break
            except Exception:
                pass
            time.sleep(0.5)
        if not tgt:
            raise RuntimeError("page target not found")

        cdp = CDP(tgt["webSocketDebuggerUrl"])
        cdp.send("Page.enable")
        cdp.send("Runtime.enable")
        cdp.send("Emulation.setDeviceMetricsOverride", {
            "width": size, "height": height, "deviceScaleFactor": 1, "mobile": False,
        })
        time.sleep(1.0)
        r = cdp.send("Page.captureScreenshot", {"format": "png", "fromSurface": True}, timeout=30)
        data = (r.get("result") or {}).get("data")
        if not data:
            raise RuntimeError("no screenshot data")
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "wb") as f:
            f.write(base64.b64decode(data))
        print("ok ->", out_path, os.path.getsize(out_path), "bytes")
        return 0
    finally:
        if cdp:
            cdp.close()
        try:
            proc.kill()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
