"""見張り（Board）と、Dashboard・API を出す HTTP サーバー。"""
from __future__ import annotations

import json
import re
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from .judge import STATES, build_items, settle
from .sources import FetchError

DASHBOARD = Path(__file__).with_name("dashboard.html")
WRITE_HEADER = "X-Dashboard"


class Board:
    """見直しのたびに材料を取り直して、カードの一覧を作り直す。取れなかった回は、前の一覧を残してエラーを出す。"""

    def __init__(self, source, interval: int = 60):
        self.source, self.interval = source, interval
        self.mu = threading.Lock()
        self.wake = threading.Event()
        self.items: list[dict] = []
        self.updated_at: str | None = None
        self.error: str | None = None
        self.checking = False
        self.mergeable: dict[int, str] = {}

    def tick(self) -> None:
        self.checking = True
        try:
            got = self.source.fetch()
            items = build_items(got["worktrees"], settle(got["prs"], self.mergeable), got["closed"], got["me"])
        except (FetchError, json.JSONDecodeError, OSError) as e:
            error = f"取得できなかった: {e}"
        else:
            error = None
        finally:
            self.checking = False
        with self.mu:
            if error is None:
                self.items, self.updated_at = items, datetime.now(timezone.utc).isoformat(timespec="seconds")
            self.error = error

    def loop(self, first: bool = True) -> None:
        """見直しを繰り返す。first が False なら、最初の 1 回は済んでいるものとして間隔を待つ。"""
        while True:
            self.wake.clear()
            started = time.time()
            if first:
                self.tick()
            first = True
            # 眠っている間は単調時計が進まないので、壁時計で間隔を測る
            while (left := started + self.interval - time.time()) > 0 and not self.wake.wait(min(30, left)):
                pass

    def view(self) -> dict:
        with self.mu:
            return {"repo": self.source.repo, "updated_at": self.updated_at, "error": self.error,
                    "checking": self.checking, "states": STATES, "worktrees": self.items}


class Handler(BaseHTTPRequestHandler):
    board: Board  # serve() で差し込む

    def log_message(self, *args) -> None:  # アクセスのたびにはログを書かない
        pass

    def reply(self, code: int, body, ctype: str = "application/json; charset=utf-8") -> None:
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def route(self, method: str) -> None:
        # DNS を差し替えて、ほかのサイトの名前のまま届くのを防ぐ
        host = re.sub(r":\d+$", "", self.headers.get("Host", ""))
        if host not in ("localhost", "127.0.0.1"):
            return self.reply(403, {"error": "localhost 以外の名前では受けない"})
        # 独自のヘッダーは、ほかのサイトのページからは付けて送れない（付けると事前確認で止まる）
        if method != "GET" and self.headers.get(WRITE_HEADER) != "1":
            return self.reply(403, {"error": f"{WRITE_HEADER} ヘッダーが無い"})
        path = urlsplit(self.path).path
        if method == "GET" and path == "/":
            return self.reply(200, DASHBOARD.read_bytes(), "text/html; charset=utf-8")
        if method == "GET" and path == "/api/worktrees":
            return self.reply(200, self.board.view())
        if method == "POST" and path == "/api/refresh":
            self.board.wake.set()
            return self.reply(202, {"checking": True})
        return self.reply(404, {"error": "無い"})

    def do_GET(self) -> None:
        self.route("GET")

    def do_POST(self) -> None:
        self.route("POST")


def serve(board: Board, port: int) -> int:
    """board は、最初の 1 回を見直し済みのもの。"""
    try:
        server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    except OSError as e:
        print(f"ポート {port} を使えない: {e}（--port で別のポートを選ぶ）")
        return 1
    Handler.board = board
    threading.Thread(target=board.loop, args=(False,), daemon=True).start()
    print(f"Dashboard: http://localhost:{port}（{board.interval} 秒おきに見直す。止めるのは Ctrl-C）", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0
