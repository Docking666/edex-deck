#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Local control service for eDEX-Deck — the "settings" entry point.

Serves a settings page on http://127.0.0.1:8899/ and a small JSON API:

    GET  /api/windows    candidate native windows (Windows only)
    GET  /api/state      current config + what is attached right now
    POST /api/attach     {"hwnd":"0x..","rect":[x,y,w,h]}  attach a native window
    POST /api/detach     {"hwnd":"0x.."}
    POST /api/embed      {"url":"..."}                      embed a Web UI now
    POST /api/profile    save the current choice into edex-deck.json

While running it also keeps an attached native window aligned with the
renderer's #main_shell — the same rectangle a BrowserView would get — so the
window follows layout switches instead of freezing at its attach-time position.
"""

import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import window_embed

IS_WIN = sys.platform == "win32"

HERE = os.path.dirname(os.path.abspath(__file__))
SETTINGS_HTML = os.path.join(HERE, "settings.html")


# Shell-like processes whose loss would wreck the user environment. Never
# kill these automatically, even if they hold the port — it's not worth
# self-harm just to clean up an exotic state.
SHELL_PROCESS_NAMES = {
    "powershell.exe", "pwsh.exe", "wscript.exe", "cscript.exe",
    "cmd.exe", "bash.exe", "wsl.exe", "msys2.exe", "git-bash.exe",
    "explorer.exe", "dwm.exe", "winlogon.exe",
    "code.exe", "code - insiders.exe", "cursor.exe",
    "msedge.exe", "chrome.exe", "firefox.exe",
    "WindowServer.exe",
}


def _pid_to_name(pid):
    try:
        out = subprocess.run(
            ["tasklist", "/NH", "/FO", "CSV", "/FI", "PID eq %d" % pid],
            capture_output=True, text=True, timeout=3,
        )
    except Exception:
        return None
    line = (out.stdout or "").strip().splitlines()
    if not line:
        return None
    return line[0].split('","')[0].strip('" ').lower()


def _kill_other_edex_deck():
    """Find and kill any process holding port 8899 except ourselves.

    Two passes: the obvious one (anything named edex-deck.exe), then a belt-
    and-braces one (anyone netstat reports as LISTENING on the port, except
    shell-like processes that must never be killed). Pass 2 catches things like
    a stray `python src/inject.py --keep` that occupied the port during
    manual testing.
    """
    if not IS_WIN:
        return []
    my_pid = os.getpid()
    killed = []
    refused = []

    # Pass 1: any old edex-deck.exe still running
    try:
        out = subprocess.run(
            ["tasklist", "/NH", "/FO", "CSV", "/FI", "IMAGENAME eq edex-deck.exe"],
            capture_output=True, text=True, timeout=5,
        )
        for line in (out.stdout or "").splitlines():
            parts = [p.strip('" ') for p in line.split('","')]
            if len(parts) < 2 or "edex-deck" not in parts[0].lower():
                continue
            try:
                pid = int(parts[1])
            except ValueError:
                continue
            if pid == my_pid:
                continue
            try:
                subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                               capture_output=True, timeout=5)
                killed.append(pid)
            except Exception:
                pass
    except Exception:
        pass

    # Pass 2: anyone LISTENING on 127.0.0.1:8899 — regardless of name.
    try:
        out = subprocess.run(
            ["netstat", "-ano"], capture_output=True, text=True, timeout=5,
        )
        port_pids = set()
        for line in (out.stdout or "").splitlines():
            if ":8899" not in line or "LISTENING" not in line:
                continue
            parts = line.split()
            if len(parts) < 5:
                continue
            try:
                port_pids.add(int(parts[-1]))
            except ValueError:
                pass
        for pid in port_pids:
            if pid == my_pid or pid in killed:
                continue
            name = _pid_to_name(pid)
            if name in SHELL_PROCESS_NAMES:
                refused.append(pid)
                continue
            try:
                subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                               capture_output=True, timeout=5)
                killed.append(pid)
            except Exception:
                pass
    except Exception:
        pass

    return killed, refused

_state = {
    "cdp": None,            # CDP instance for the eDEX renderer
    "attached": None,       # {"hwnd": int, "old_style": int, "parent": int}
    "config_path": None,
    "app_dir": None,
    "last_embed": None,     # callable that re-embeds the current URL
}


# ------------------------------------------------------------------ helpers

def _read_body(handler):
    n = int(handler.headers.get("Content-Length") or 0)
    if n <= 0:
        return {}
    try:
        return json.loads(handler.rfile.read(n).decode("utf-8"))
    except Exception as e:
        return {"_error": str(e)}


def _main_shell_rect():
    cdp = _state.get("cdp")
    if not cdp:
        return None
    raw = cdp.ev(
        "(function(){var e=document.querySelector('#main_shell');"
        "if(!e)return 'null';"
        "var r=e.getBoundingClientRect();"
        "return JSON.stringify({x:r.x,y:r.y,w:r.width,h:r.height});})()"
    )
    try:
        d = json.loads(raw)
        return (d["x"], d["y"], d["w"], d["h"])
    except Exception:
        return None


def _attach(hwnd, rect):
    w32 = window_embed.api()
    edex = w32.find_by_exe("eDEX-UI.exe")
    if not edex:
        return None, "eDEX window not found"
    if _state.get("attached"):
        _detach()
    old = w32.attach(hwnd, edex["hwnd"], *rect)
    if old is None:
        return None, "SetParent failed (error %s)" % ctypes_get_last_error()
    _state["attached"] = {"hwnd": hwnd, "old_style": old, "parent": edex["hwnd"]}
    return {"hwnd": hwnd, "rect": list(rect)}, None


def _detach():
    w32 = window_embed.api()
    a = _state.get("attached")
    if not a:
        return {"detached": False}
    w32.detach(a["hwnd"], a.get("old_style"))
    _state["attached"] = None
    return {"detached": True, "hwnd": a["hwnd"]}


def ctypes_get_last_error():
    import ctypes
    return ctypes.get_last_error()


def _save_profile(name, body):
    """Write the current choice back into edex-deck.json so it survives restarts."""
    cfg_path = _state.get("config_path")
    if not cfg_path or not os.path.exists(cfg_path):
        return None, "config file not found: %s" % cfg_path
    try:
        with open(cfg_path, encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception as e:
        return None, "cannot read config: %s" % e

    prof = {}
    mode = body.get("mode")
    if mode == "window":
        prof["desc"] = "Native window: %s" % body.get("title", "")
        prof["attachHwnd"] = body.get("hwnd")
        prof["attachTitle"] = body.get("title", "")
    elif mode == "url":
        prof["desc"] = "Web UI: %s" % body.get("url", "")
        prof["url"] = body.get("url")
    elif mode == "static":
        prof["desc"] = "Local folder: %s" % body.get("serveStatic", "")
        prof["serveStatic"] = body.get("serveStatic")
        prof["url"] = body.get("url")
    else:
        return None, "unknown mode: %s" % mode

    profiles = cfg.setdefault("profiles", {})
    profiles[name] = prof
    if body.get("makeDefault"):
        cfg["defaultProfile"] = name
    try:
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
    except Exception as e:
        return None, "cannot write config: %s" % e
    return {"saved": name, "path": cfg_path}, None


# ------------------------------------------------------------------ alignment loop

def _alignment_loop(stop_event):
    """Keep the attached native window glued to #main_shell.

    ResizeObserver handles the BrowserView, but a native window has no JS-side
    representation — the only way for it to follow layout switches is for this
    side to keep asking where the shell is now.
    """
    while not stop_event.is_set():
        try:
            a = _state.get("attached")
            if a:
                rect = _main_shell_rect()
                if rect:
                    w32 = window_embed.api()
                    w32.u.MoveWindow(a["hwnd"], int(rect[0]), int(rect[1]),
                                     int(rect[2]), int(rect[3]), True)
        except Exception:
            pass
        stop_event.wait(1.5)


# ------------------------------------------------------------------ http

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a, **k):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, bytes):
            data = body
        else:
            try:
                data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            except Exception as e:
                # 宁可返回一个说得清的错误，也不要发一个空响应体 ——
                # 前端 r.json() 撞上空体只会抛出难懂的 "Unexpected end of JSON input"
                data = json.dumps(
                    {"error": "serialisation failed: %s: %s" % (type(e).__name__, e)},
                    ensure_ascii=False,
                ).encode("utf-8")
                code = 500
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            try:
                with open(SETTINGS_HTML, "rb") as f:
                    return self._send(200, f.read(), "text/html; charset=utf-8")
            except Exception as e:
                return self._send(500, {
                    "error": "settings.html is not readable at %s. In a packaged "
                             "build this means it was bundled without --add-data; "
                             "rebuild using tools/build.py. (%s)" % (SETTINGS_HTML, e)
                })
        if path == "/api/windows":
            try:
                return self._send(200, {"windows": window_embed.api().list_windows()})
            except Exception as e:
                return self._send(500, {"error": str(e)})
        if path == "/api/state":
            a = _state.get("attached")
            return self._send(200, {
                "attached": {"hwnd": "0x%08X" % a["hwnd"]} if a else None,
                "cdp": bool(_state.get("cdp")),
            })
        # silence the favicon probe so it doesn't pollute logs / look like a real error
        if path == "/favicon.ico":
            return self._send(204, b"")
        return self._send(404, {"error": "no such endpoint: " + path})

    def do_POST(self):
        path = self.path.split("?")[0]
        body = _read_body(self)
        if body.get("_error"):
            return self._send(400, {"error": body["_error"]})
        try:
            if path == "/api/attach":
                hwnd = int(str(body.get("hwnd", "0")), 16) \
                    if str(body.get("hwnd", "")).startswith("0x") \
                    else int(body.get("hwnd", 0))
                rect = body.get("rect") or _main_shell_rect() or [0, 0, 800, 600]
                res, err = _attach(hwnd, rect)
                return self._send(200 if res else 400, res or {"error": err})
            if path == "/api/detach":
                return self._send(200, _detach())
            if path == "/api/embed":
                fn = _state.get("last_embed")
                if not fn:
                    return self._send(400, {"error": "no embed function registered"})
                fn(body.get("url", ""))
                return self._send(200, {"embedding": body.get("url")})
            if path == "/api/profile":
                res, err = _save_profile(body.get("name", ""), body)
                return self._send(200 if res else 400, res or {"error": err})
            return self._send(404, {"error": "not found"})
        except Exception as e:
            return self._send(500, {"error": "%s: %s" % (type(e).__name__, e)})


def start(port, cdp=None, config_path=None, app_dir=None, embed_fn=None):
    """Start the control service + alignment thread. Returns the HTTPServer."""
    _state["cdp"] = cdp
    _state["config_path"] = config_path
    _state["app_dir"] = app_dir
    _state["last_embed"] = embed_fn

    httpd = None
    last_err = None
    for _ in range(2):
        try:
            httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
            break
        except OSError as e:
            last_err = e
            killed, refused = _kill_other_edex_deck()
            if not killed:
                msg = "port %d already in use (%s). " % (port, e)
                if refused:
                    msg += ("A shell-like process (PID %s) is occupying the port "
                            "and was left alone on purpose; close that process or "
                            "its parent terminal, then start again." % ", ".join(map(str, refused)))
                else:
                    msg += ("An older eDEX-Deck instance is still running; close eDEX "
                             "(and any leftover edex-deck.exe), then start again.")
                raise RuntimeError(msg) from e
            # Give Windows a moment to release the socket
            time.sleep(0.6)
    if httpd is None:
        raise RuntimeError("could not bind port %d: %s" % (port, last_err))

    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    stop = threading.Event()
    threading.Thread(target=_alignment_loop, args=(stop,), daemon=True).start()
    httpd._deck_stop = stop
    return httpd
