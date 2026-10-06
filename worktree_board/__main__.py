"""python3 -m worktree_board serve|status"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .judge import STATES
from .server import Board, serve
from .sources import FetchError, Source


def status(board: Board) -> int:
    board.tick()
    if board.error:
        print(board.error)
        return 1
    if not board.items:
        print("見るものが無い（この repo に、自分の開いている PR も、primary checkout 以外の worktree も無い）")
    for state in STATES:
        rows = [i for i in board.items if i["state"] == state]
        if rows:
            print(f"{state} {len(rows)}")
            for i in rows:
                marks = f"  [{'・'.join(i['badges'])}]" if i["badges"] else ""
                print(f"  {i['label']}  {i['reason']}{marks}")
    return 0


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="worktree_board", description="自分の worktree と PR の「今ボールを持っているのは誰か」を見る")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--repo", help="OWNER/REPO（省略すると、checkout の origin から gh が決める）")
    common.add_argument("--checkout", type=Path, default=Path.cwd(), help="repo の中のフォルダ（省略すると今のフォルダ）")
    sub = p.add_subparsers(dest="cmd", required=True)
    ps = sub.add_parser("serve", parents=[common], help="Dashboard を出して、定期的に見直す")
    ps.add_argument("--port", type=int, default=8765)
    ps.add_argument("--interval", type=int, default=60, help="見直す間隔（秒）")
    sub.add_parser("status", parents=[common], help="今の状態を 1 回だけ表示する")
    a = p.parse_args(argv)
    board = Board(Source(a.checkout.resolve(), a.repo), getattr(a, "interval", 60))
    try:
        if a.cmd == "status":
            return status(board)
        board.tick()  # 最初の 1 回は待たずに取り、repo や認証の誤りをすぐ知らせる
        if board.error:
            print(board.error, file=sys.stderr)
            return 1
        return serve(board, a.port)
    except FetchError as e:
        print(e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
