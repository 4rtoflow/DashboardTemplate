"""python3 -m worktree_board serve|status"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import i18n
from .judge import STATES
from .server import Board, serve
from .sources import Source


def status(board: Board, msgs: dict) -> int:
    board.tick()
    if board.error:
        print(i18n.describe_error(msgs, board.error))
        return 1
    if not board.items:
        print(i18n.fmt(msgs, "cli.empty"))
    for state in STATES:
        rows = [i for i in board.items if i["state"] == state]
        if rows:
            print(i18n.fmt(msgs, "ui.column_label", {"state": i18n.fmt(msgs, f"state.{state}"), "n": len(rows)}))
            for i in rows:
                marks = f"  [{' / '.join(i18n.fmt(msgs, b) for b in i['badges'])}]" if i["badges"] else ""
                print(f"  {i['label']}  {i18n.fmt(msgs, i['reason']['key'], i['reason']['args'])}{marks}")
    return 0


def pick_language(argv: list[str]) -> str:
    """--lang があればそれ、無ければ環境変数から。--help の文章も選んだ言語で出すので、本体の解析より先に決める。"""
    pre = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    pre.add_argument("--lang")
    known, _ = pre.parse_known_args(argv)
    return i18n.normalize(known.lang) or i18n.detect()


def main(argv: list[str]) -> int:
    msgs = i18n.catalog(pick_language(argv))
    t = lambda key: msgs[key].replace("%", "%%")  # argparse の書式として読まれないように
    p = argparse.ArgumentParser(prog="worktree_board", description=t("cli.description"))
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--repo", help=t("cli.help_repo"))
    common.add_argument("--checkout", type=Path, default=Path.cwd(), help=t("cli.help_checkout"))
    lang_help = t("cli.help_lang") + f" [{', '.join(i18n.available())}]"
    common.add_argument("--lang", default=argparse.SUPPRESS, help=lang_help)  # サブコマンドの後ろでも、前でも置ける
    p.add_argument("--lang", help=lang_help)
    sub = p.add_subparsers(dest="cmd", required=True)
    ps = sub.add_parser("serve", parents=[common], help=t("cli.help_serve"))
    ps.add_argument("--port", type=int, default=8765, help=t("cli.help_port"))
    ps.add_argument("--interval", type=int, default=60, help=t("cli.help_interval"))
    sub.add_parser("status", parents=[common], help=t("cli.help_status"))
    a = p.parse_args(argv)
    board = Board(Source(a.checkout.resolve(), a.repo), getattr(a, "interval", 60))
    if a.cmd == "status":
        return status(board, msgs)
    board.tick()  # 最初の 1 回は待たずに取り、repo や認証の誤りをすぐ知らせる
    if board.error:
        print(i18n.describe_error(msgs, board.error), file=sys.stderr)
        return 1
    return serve(board, a.port, msgs)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
