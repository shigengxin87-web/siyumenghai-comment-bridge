#!/usr/bin/env python3
"""Local same-origin bridge for the Siyumenghai comment helper."""

from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import json
import os
import socket
import subprocess


HOST = "127.0.0.1"
PORT = 2024
UPSTREAM = "http://127.0.0.1:2022"
ROOT = Path(__file__).resolve().parent
BUNDLED_BRIDGE = ROOT / "index.html"
REMOTE_BRIDGE = "https://shigengxin87-web.github.io/siyumenghai-comment-bridge/?v=20260814-1"
BRIDGE_VERSION = "20260814-1"
SUPPORT_ROOT = Path.home() / "Library/Application Support/Siyumenghai Video Comment Helper"
LOG_PATH = SUPPORT_ROOT / "comment-bridge-access.log"
HELPER_LAUNCHER = SUPPORT_ROOT / "启动评论助手.command"
ALLOWED_ORIGINS = {
    "https://shigengxin87-web.github.io",
    "https://siyumenghai.cn",
    "https://www.siyumenghai.cn",
    "http://127.0.0.1:2024",
    "http://localhost:2024",
}
ALLOWED_PATHS = {
    "/api/channels/feed/profile",
    "/api/channels/feed/comment/list",
}


def load_bridge_html() -> bytes:
    """Prefer the installed bridge so extraction never depends on live GitHub Pages."""
    try:
        body = BUNDLED_BRIDGE.read_text(encoding="utf-8")
    except OSError:
        response = subprocess.run(
            [
                "/usr/bin/curl",
                "-fsSL",
                "--max-time",
                "20",
                "-H",
                "Cache-Control: no-cache",
                REMOTE_BRIDGE,
            ],
            capture_output=True,
            check=True,
            timeout=25,
        )
        body = response.stdout.decode("utf-8")
    return body.replace(
        "const API = 'http://127.0.0.1:2024';",
        "const API = location.origin;",
    ).encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    def helper_running(self):
        try:
            with socket.create_connection(("127.0.0.1", 2022), timeout=0.25):
                return True
        except OSError:
            return False

    def send_json(self, status, value):
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def cors(self):
        origin = self.headers.get("Origin", "")
        if origin in ALLOWED_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Accept, Content-Type")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Cache-Control", "no-store")

    def do_OPTIONS(self):
        self.send_response(204)
        self.cors()
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/status":
            self.send_json(
                200,
                {
                    "ok": True,
                    "version": BRIDGE_VERSION,
                    "installed": HELPER_LAUNCHER.is_file(),
                    "running": self.helper_running(),
                    "bundled_bridge": BUNDLED_BRIDGE.is_file(),
                },
            )
            return
        if path == "/extract":
            try:
                body = load_bridge_html()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
                self.send_header("Pragma", "no-cache")
                self.send_header("Expires", "0")
                self.end_headers()
                self.wfile.write(body)
            except (HTTPError, URLError, TimeoutError, subprocess.SubprocessError, UnicodeError) as error:
                body = f"评论页面载入失败，请检查本地安装后重试：{error}".encode("utf-8")
                self.send_response(502)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            return
        if path not in ALLOWED_PATHS:
            self.send_response(404)
            self.cors()
            self.end_headers()
            return
        try:
            request = Request(UPSTREAM + self.path, headers={"Accept": "application/json"})
            with urlopen(request, timeout=20) as response:
                body = response.read()
                self.send_response(response.status)
                self.cors()
                self.send_header("Content-Type", response.headers.get("Content-Type", "application/json; charset=utf-8"))
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        except HTTPError as error:
            body = error.read()
            self.send_response(error.code)
            self.cors()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (URLError, TimeoutError) as error:
            message = error.reason if isinstance(error, URLError) else error
            self.send_json(503, {"code": 503, "msg": f"本地评论助手未连接：{message}"})

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path != "/launch":
            self.send_json(404, {"ok": False, "message": "not found"})
            return
        if self.headers.get("Origin", "") not in ALLOWED_ORIGINS:
            self.send_json(403, {"ok": False, "message": "origin not allowed"})
            return
        if self.helper_running():
            self.send_json(200, {"ok": True, "installed": True, "running": True, "launched": False})
            return
        if not HELPER_LAUNCHER.is_file():
            self.send_json(404, {"ok": False, "installed": False, "running": False})
            return
        try:
            subprocess.Popen(
                ["/usr/bin/open", "-a", "Terminal", str(HELPER_LAUNCHER)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self.send_json(202, {"ok": True, "installed": True, "running": False, "launched": True})
        except OSError as error:
            self.send_json(500, {"ok": False, "installed": True, "running": False, "message": str(error)})

    def log_message(self, format, *args):
        SUPPORT_ROOT.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as log:
            log.write(f"{datetime.now().isoformat(timespec='seconds')} {format % args}\n")


if __name__ == "__main__":
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
