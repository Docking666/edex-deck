#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
eDEX-Deck — non-invasive injector for eDEX-UI.

Injects the layout dock (and optionally any local Web UI) into a running
eDEX-UI instance over the Chrome DevTools Protocol.

Nothing on disk is modified: no files in the install directory, no changes to
settings.json. Everything happens at runtime and disappears when eDEX exits.

Examples
--------
    # layout dock only
    python inject.py

    # also embed a local Web UI
    python -m http.server 8898 --directory examples
    python inject.py --url "http://127.0.0.1:8898/demo-ui.html"

    # or let the injector start the server and read its URL from stdout
    python inject.py --serve "mytool --serve --port 8898"

    # embed an already-running local Web UI
    python inject.py --url "http://127.0.0.1:8898/?password=xxx"

    # keep eDEX running after injecting
    python inject.py --keep

    # capture one screenshot per layout preset (used for docs)
    python inject.py --capture-docs
"""

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request

import websocket

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from layout_kit import LAYOUT_JS  # noqa: E402

DEFAULT_DEBUG_PORT = 9333
DEFAULT_SERVE_PORT = 8898


# ------------------------------------------------------------------ helpers

def log(*a):
    print(" ".join(str(x) for x in a), flush=True)


def port_open(port, host="127.0.0.1"):
    import socket

    s = socket.socket()
    s.settimeout(0.8)
    try:
        s.connect((host, port))
        return True
    except Exception:
        return False
    finally:
        s.close()


def find_edex():
    """Locate the eDEX-UI executable using the usual per-platform paths."""
    cands = []
    if sys.platform == "win32":
        la = os.environ.get("LOCALAPPDATA", "")
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        pfx86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        cands += [
            os.path.join(la, "Programs", "eDEX-UI", "eDEX-UI.exe"),
            os.path.join(pf, "eDEX-UI", "eDEX-UI.exe"),
            os.path.join(pfx86, "eDEX-UI", "eDEX-UI.exe"),
        ]
    elif sys.platform == "darwin":
        cands += ["/Applications/eDEX-UI.app/Contents/MacOS/eDEX-UI"]
    else:
        cands += [
            "/opt/eDEX-UI/eDEX-UI",
            "/usr/local/bin/eDEX-UI",
            os.path.expanduser("~/Applications/eDEX-UI.AppImage"),
        ]
    for c in cands:
        if c and os.path.exists(c):
            return c
    return None


class CDP:
    def __init__(self, ws_url, timeout=30):
        self.ws = websocket.create_connection(ws_url, timeout=timeout, suppress_origin=True)
        self.seq = 0
        self.events = []

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
            self.events.append(msg)
        raise TimeoutError(method)

    def ev(self, expr, timeout=30):
        r = self.send(
            "Runtime.evaluate",
            {"expression": expr, "returnByValue": True, "awaitPromise": True, "userGesture": True},
            timeout=timeout,
        )
        res = r.get("result", {})
        if "exceptionDetails" in res:
            return "ERR: " + str(res["exceptionDetails"].get("text"))
        return res.get("result", {}).get("value")

    def shot(self, path, timeout=30):
        r = self.send("Page.captureScreenshot", {"format": "png", "fromSurface": True}, timeout=timeout)
        data = (r.get("result") or {}).get("data")
        if not data:
            return False
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "wb") as f:
            f.write(base64.b64decode(data))
        return True

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


# ------------------------------------------------------------------ pieces

INJECT_VIEW_JS = r"""
(() => {
  const PW = __PW__;
  const PORT = __PORT__;
  const URL = __URL__;
  const electron = require('electron');
  const r = electron.remote || (electron.default && electron.default.remote);
  if (!r) return { ok: false, why: 'no remote module' };
  const win = r.getCurrentWindow();
  const BrowserView = r.BrowserView || r.require('electron').BrowserView;
  if (!BrowserView) return { ok: false, why: 'no BrowserView' };

  const shell = document.querySelector('#main_shell');
  if (!shell) return { ok: false, why: 'no #main_shell' };
  const b = shell.getBoundingClientRect();

  const target = URL || ('http://127.0.0.1:' + PORT + '/?password=' + PW);

  const view = new BrowserView({
    webPreferences: { nodeIntegration: false, contextIsolation: true, sandbox: false }
  });
  win.setBrowserView(view);
  view.setBounds({
    x: Math.round(b.x), y: Math.round(b.y),
    width: Math.round(b.width), height: Math.round(b.height)
  });
  view.setAutoResize({ width: true, height: true });
  view.webContents.loadURL(target);
  globalThis.__edexView = view;

  return { ok: true, url: target, bounds: {
    x: Math.round(b.x), y: Math.round(b.y),
    w: Math.round(b.width), h: Math.round(b.height)
  }};
})()
"""

# Some UIs are built for newer Chromium than the host ships. Inject a tiny
# polyfill set before the page's own scripts run.
POLYFILL = r"""
(function () {
  var def = function (o, k, f) {
    try { Object.defineProperty(o, k, { value: f, writable: true, configurable: true }); } catch (e) {}
  };
  if (!Object.hasOwn) {
    def(Object, 'hasOwn', function (o, p) { return Object.prototype.hasOwnProperty.call(o, p); });
  }
  if (!Array.prototype.at) {
    def(Array.prototype, 'at', function (n) {
      n = Math.trunc(n) || 0; if (n < 0) n += this.length;
      return (n < 0 || n >= this.length) ? undefined : this[n];
    });
  }
  if (!String.prototype.at) {
    def(String.prototype, 'at', function (n) {
      n = Math.trunc(n) || 0; if (n < 0) n += this.length;
      return (n < 0 || n >= this.length) ? undefined : this[n];
    });
  }
  if (!Array.prototype.findLast) {
    def(Array.prototype, 'findLast', function (f, t) {
      for (var i = this.length - 1; i >= 0; i--) { if (f.call(t, this[i], i, this)) return this[i]; }
      return undefined;
    });
  }
  if (!Array.prototype.findLastIndex) {
    def(Array.prototype, 'findLastIndex', function (f, t) {
      for (var i = this.length - 1; i >= 0; i--) { if (f.call(t, this[i], i, this)) return i; }
      return -1;
    });
  }
  if (!Array.prototype.flat) {
    def(Array.prototype, 'flat', function (d) {
      d = (d === undefined) ? 1 : d; var r = [];
      var go = function (a, dd) {
        for (var i = 0; i < a.length; i++) {
          var x = a[i];
          if (Array.isArray(x) && dd > 0) { go(x, dd - 1); } else { r.push(x); }
        }
      };
      go(this, d); return r;
    });
  }
  if (!Array.prototype.flatMap) {
    def(Array.prototype, 'flatMap', function (f, t) {
      var r = [];
      for (var i = 0; i < this.length; i++) {
        var v = f.call(t, this[i], i, this);
        if (Array.isArray(v)) { for (var j = 0; j < v.length; j++) r.push(v[j]); } else { r.push(v); }
      }
      return r;
    });
  }
  if (typeof structuredClone === 'undefined') {
    def(globalThis, 'structuredClone', function (v) { return JSON.parse(JSON.stringify(v)); });
  }
})();
"""

# eDEX's update checker throws an uncaught error when it can't reach GitHub,
# which pops a modal over the UI. It appears asynchronously, so guard on a timer.
KILL_ERR_MODAL_JS = r"""
(function () {
  if (globalThis.__edexDeckErrGuard) return 'already';
  var kill = function () {
    var n = 0;
    document.querySelectorAll('section#modal,div#modal,[id*=modal]').forEach(function (m) {
      var t = (m.textContent || '');
      if (/PANIC|RELOAD|Uncaught|ETIMEDOUT|ENOTFOUND/i.test(t)) { m.remove(); n++; }
    });
    return n;
  };
  kill();
  globalThis.__edexDeckErrGuard = setInterval(kill, 1500);
  return 'guard-installed';
})()
"""

READY_JS = (
    "(()=>{try{return JSON.stringify({rs:document.readyState,"
    "body:!!document.body,"
    "n:document.body?document.body.querySelectorAll('*').length:0,"
    "shell:!!document.querySelector('#main_shell'),"
    "xterm:!!document.querySelector('.xterm')});}"
    "catch(e){return JSON.stringify({err:String(e)})}})()"
)


# ------------------------------------------------------------------ main

def main():
    ap = argparse.ArgumentParser(description="eDEX-Deck injector")
    ap.add_argument("--edex", help="path to the eDEX-UI executable")
    ap.add_argument("--profile", help="named profile from edex-deck.json")
    ap.add_argument("--config", help="path to a profiles file (default: ./edex-deck.json)")
    ap.add_argument("--debug-port", type=int, default=DEFAULT_DEBUG_PORT)
    ap.add_argument("--serve", help="command that starts a local Web UI; its stdout is parsed for a URL")
    ap.add_argument("--serve-port", type=int, default=DEFAULT_SERVE_PORT)
    ap.add_argument("--url", help="embed this URL instead of starting a server")
    ap.add_argument("--no-layout", action="store_true", help="skip the layout dock")
    ap.add_argument("--keep", action="store_true", help="leave eDEX and the server running")
    ap.add_argument("--capture-docs", action="store_true",
                    help="step through every layout preset and save screenshots into --outdir")
    ap.add_argument("--system-shot",
                    help="after injecting, grab the whole screen to this PNG "
                         "(needed to capture embedded native views)")
    ap.add_argument("--outdir", default=os.path.join(HERE, "..", "docs", "screenshots"))
    args = ap.parse_args()

    # Profile lookup. CLI flags always win over the profile, so any value can
    # be overridden on the command line.
    cfg_path = args.config or os.path.join(os.path.dirname(HERE), "edex-deck.json")
    profiles = {}
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, encoding="utf-8") as f:
                profiles = json.load(f).get("profiles", {}) or {}
        except Exception as e:
            log("[warn] could not read config:", cfg_path, e)

    if args.profile:
        p = profiles.get(args.profile)
        if p is None:
            log("[error] unknown profile:", args.profile)
            log("[error] available:", ", ".join(sorted(profiles)) or "(none)")
            return 2
        log("[profile]", args.profile, "-", p.get("desc", ""))
        if p.get("serve"):
            sp = p.get("servePort", args.serve_port)
            cmd = (
                p["serve"]
                .replace("{port}", str(sp))
                # {python} 指向当前解释器，避免依赖 PATH 里的 python
                .replace("{python}", '"%s"' % sys.executable)
            )
            args.serve = args.serve or cmd
            args.serve_port = sp
        if p.get("url"):
            args.url = args.url or p["url"]

    edex = args.edex or find_edex()
    if not edex:
        log("[error] eDEX-UI not found. Pass --edex <path>.")
        return 2
    if not os.path.exists(edex):
        log("[error] not found:", edex)
        return 2
    log("[edex]", edex)

    serve_proc = None
    password = None
    embed_url = args.url

    if args.serve:
        log("[serve] starting:", args.serve)
        serve_proc = subprocess.Popen(
            args.serve, shell=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
        )
        captured = {"pw": None, "url": None}

        def reader():
            for line in serve_proc.stdout:
                log("[serve]", line.rstrip())
                m = re.search(r"(https?://\S+password=\S+)", line)
                if m:
                    captured["url"] = m.group(1)
                m2 = re.search(r"password=([A-Za-z0-9_\-]+)", line)
                if m2:
                    captured["pw"] = m2.group(1)

        threading.Thread(target=reader, daemon=True).start()
        # 端口起来就够 —— password 只在需要现拼 URL 时才用得上
        for _ in range(40):
            if port_open(args.serve_port):
                break
            time.sleep(0.5)
        password = captured["pw"]
        if captured["url"]:
            embed_url = captured["url"]
        log("[serve] ready, password:", "yes" if password else "no")

    # Launch eDEX with the debugging port.
    # NOTE: if ELECTRON_RUN_AS_NODE is set in this shell (common when a parent
    # app is itself Electron-based), the binary degrades to plain Node and
    # rejects every --flag with "bad option". Strip it.
    env = os.environ.copy()
    for k in ("ELECTRON_RUN_AS_NODE", "ELECTRON_NO_ATTACH_CONSOLE", "NODE_OPTIONS"):
        env.pop(k, None)

    cmd = [edex, "--nointro", "--remote-debugging-port=%d" % args.debug_port]
    log("[edex] launching:", " ".join(cmd))
    edex_proc = subprocess.Popen(cmd, env=env)

    try:
        for _ in range(40):
            if port_open(args.debug_port):
                break
            time.sleep(1)
        else:
            log("[error] debug port never opened")
            return 3

        # find the renderer target
        tgt = None
        for _ in range(30):
            try:
                with urllib.request.urlopen(
                    "http://127.0.0.1:%d/json/list" % args.debug_port, timeout=5
                ) as r:
                    ts = json.load(r)
                tgt = next(
                    (t for t in ts if t.get("type") == "page" and "ui.html" in str(t.get("url"))),
                    None,
                )
                if tgt:
                    break
            except Exception:
                pass
            time.sleep(1)
        if not tgt:
            log("[error] renderer target not found")
            return 3

        cdp = CDP(tgt["webSocketDebuggerUrl"])
        log("[cdp] connected")
        cdp.send("Page.enable")
        cdp.send("Runtime.enable")
        cdp.send("Log.enable")

        # wait for the dynamically-built UI
        for _ in range(35):
            st = cdp.ev(READY_JS)
            try:
                d = json.loads(st)
            except Exception:
                d = {}
            if d.get("xterm") and d.get("n", 0) > 100:
                log("[wait] ui ready")
                break
            time.sleep(2)
        time.sleep(1.5)

        log("[cleanup-ui]", cdp.ev(KILL_ERR_MODAL_JS))

        # optional: embed an external Web UI
        if embed_url or args.serve:
            js = (INJECT_VIEW_JS
                  .replace("__PW__", json.dumps(password or ""))
                  .replace("__PORT__", str(args.serve_port))
                  .replace("__URL__", json.dumps(embed_url or "")))
            log("[inject] embedding web ui ...")
            log("[inject]", json.dumps(cdp.ev(js), ensure_ascii=False)[:400])

            # polyfill for UIs built against a newer Chromium
            vt = None
            for _ in range(15):
                try:
                    with urllib.request.urlopen(
                        "http://127.0.0.1:%d/json/list" % args.debug_port, timeout=5
                    ) as r:
                        cur = json.load(r)
                    vt = next(
                        (t for t in cur if str(args.serve_port) in str(t.get("url") or "")),
                        None,
                    )
                    if vt:
                        break
                except Exception:
                    pass
                time.sleep(1)
            if vt:
                vcdp = CDP(vt["webSocketDebuggerUrl"])
                vcdp.send("Page.enable")
                vcdp.send("Runtime.enable")
                vcdp.send("Page.addScriptToEvaluateOnNewDocument", {"source": POLYFILL})
                vcdp.send("Page.reload")
                # 别只认 #root —— 那是 React 的约定，纯静态页没有它。
                # 用「文档加载完成 + 有实质内容」来判断。
                for _ in range(20):
                    time.sleep(1.5)
                    s = vcdp.ev(
                        "JSON.stringify({rs:document.readyState,"
                        "len:document.body?document.body.innerHTML.length:0,"
                        "kids:(document.getElementById('root')||{children:[]}).children.length})"
                    )
                    try:
                        d = json.loads(s)
                    except Exception:
                        continue
                    if d.get("rs") == "complete" and (
                        d.get("len", 0) > 500 or d.get("kids", 0) > 0
                    ):
                        log("[inject] web ui rendered, body length:", d.get("len"))
                        break
                else:
                    log("[inject] web ui did not render (may need newer Chromium APIs)")
            else:
                log("[inject] embedded target not found")

        # layout dock
        if not args.no_layout:
            log("[layout] injecting dock ...")
            log("[layout]", json.dumps(cdp.ev(LAYOUT_JS), ensure_ascii=False)[:400])

        if args.capture_docs:
            outdir = os.path.abspath(args.outdir)
            for name in ("default", "cockpit", "focus"):
                cdp.ev(
                    "(function(){var b=document.querySelector('#__edex_layout_ctl "
                    "[data-layout=\"%s\"]');if(!b)return 'no-btn';b.click();return 'ok';})()" % name
                )
                time.sleep(4)
                p = os.path.join(outdir, "layout-%s.png" % name)
                log("[docs]", name, "->", p, cdp.shot(p))

        if args.system_shot:
            time.sleep(2.5)
            try:
                from screenshot import capture as sys_capture
                p = os.path.abspath(args.system_shot)
                log("[shot]", p, sys_capture(p))
            except Exception as e:
                log("[shot] failed:", type(e).__name__, str(e))

        if args.keep:
            log("[keep] running — close eDEX to stop.")
            while edex_proc.poll() is None:
                time.sleep(2)
            log("[keep] eDEX exited")
    finally:
        if not args.keep:
            taskkill = ["taskkill", "/F", "/IM", os.path.basename(edex)] if sys.platform == "win32" else None
            if taskkill:
                subprocess.run(taskkill, capture_output=True)
            else:
                try:
                    edex_proc.kill()
                except Exception:
                    pass
            if serve_proc:
                try:
                    serve_proc.kill()
                except Exception:
                    pass
            log("[cleanup] done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
