"""worktree と PR から、カードの状態を決める。副作用は無く、テストはここを見る。

状態は上から順に当てはめて決める（先に当たった規則が勝つ）。
  自分でしか動かせないもの（コンフリクト・CI の失敗・変更の要求）を先に、
  自動で進むもの（CI の実行中）を次に、そのあとに人を待つもの（Draft・レビュー）を見る。
"""
from __future__ import annotations

import re
from pathlib import Path

STATES = ["自分の番", "GitHub 待ち", "レビュー待ち", "完了"]
FAILED = {"FAILURE", "TIMED_OUT", "STARTUP_FAILURE", "ACTION_REQUIRED", "ERROR"}


def login(item: dict) -> str:
    return (item.get("author") or {}).get("login") or ""


def run_id(url: str | None) -> int:
    m = re.search(r"/actions/runs/(\d+)", url or "")
    return int(m.group(1)) if m else 0


def failed_checks(pr: dict) -> list[str]:
    """失敗しているチェックの名前。同じチェックは最新の run だけを見る（再実行で通ったものを数えない）。"""
    latest: dict[str, tuple[int, str | None]] = {}
    for c in pr.get("statusCheckRollup") or []:
        if c.get("__typename") == "StatusContext":
            latest[f"status/{c.get('context')}"] = (0, c.get("state"))
            continue
        key, rid = f"{c.get('workflowName') or ''}/{c.get('name')}", run_id(c.get("detailsUrl"))
        if key not in latest or rid >= latest[key][0]:
            latest[key] = (rid, c.get("conclusion"))
    return [k for k, (_, concl) in latest.items() if concl in FAILED]


def running_checks(pr: dict) -> list[str]:
    names = []
    for c in pr.get("statusCheckRollup") or []:
        if c.get("__typename") == "StatusContext":
            if c.get("state") in ("PENDING", "EXPECTED"):
                names.append(c.get("context") or "")
        elif c.get("status") != "COMPLETED":
            names.append(f"{c.get('workflowName') or ''}/{c.get('name')}")
    return names


def reviewers(pr: dict, me: str) -> dict[str, dict]:
    """自分以外のレビュアーごとの、最後の「承認・変更の要求・取り下げ」のレビュー。コメントだけのレビューは数えない。"""
    last: dict[str, dict] = {}
    for r in sorted(pr.get("reviews") or [], key=lambda r: r.get("submittedAt") or ""):
        if login(r) != me and r.get("state") in ("APPROVED", "CHANGES_REQUESTED", "DISMISSED"):
            last[login(r)] = r
    return last


def change_requests(pr: dict, me: str) -> tuple[list[str], list[str]]:
    """変更を求めたままの人を、今の head に対して求めた人と、求めた後に push された人に分ける。"""
    on_head, pushed = [], []
    for who, r in sorted(reviewers(pr, me).items()):
        if r.get("state") == "CHANGES_REQUESTED":
            oid = (r.get("commit") or {}).get("oid")
            (on_head if oid in (None, pr.get("headRefOid")) else pushed).append(who)
    return on_head, pushed


def settle(prs: list[dict], memory: dict[int, str]) -> list[dict]:
    """mergeable は、GitHub が計算し直している間 UNKNOWN になる。その間は前回の値を使う（コンフリクトの表示が揺れない）。"""
    out = []
    for pr in prs:
        n, now = pr["number"], pr.get("mergeable") or "UNKNOWN"
        if now == "UNKNOWN":
            now = memory.get(n, "UNKNOWN")
        memory[n] = now
        out.append({**pr, "mergeable": now})
    for n in set(memory) - {pr["number"] for pr in prs}:
        del memory[n]
    return out


def turn(state: str, reason: str, next_step: str = "") -> dict:
    return {"state": state, "reason": reason, "next": next_step}


def judge(pr: dict | None, closed: dict | None, me: str) -> dict:
    """1 つの worktree の状態。pr は開いている PR、closed は同じブランチの閉じた PR（どちらも無ければ PR がまだ無い）。"""
    if pr is None and closed:
        merged = closed.get("state") == "MERGED"
        return turn("完了", f"PR #{closed['number']} が" + ("マージされた" if merged else "マージされずにクローズされた"),
                    "worktree を片付ける")
    if pr is None:
        return turn("自分の番", "PR がまだ無い", "作業を進めるか、PR を作る")
    if pr.get("mergeable") == "CONFLICTING":
        return turn("自分の番", "ベースブランチとコンフリクトしている", "ベースブランチを取り込んで解く")
    failed = failed_checks(pr)
    if failed:
        return turn("自分の番", "CI が失敗: " + "、".join(failed[:2]), "ログを見て直し、push する")
    asked, pushed = change_requests(pr, me)
    if asked:
        return turn("自分の番", f"{'、'.join(asked)} が変更を求めた", "指摘を直して push する")
    running = running_checks(pr)
    if running:
        return turn("GitHub 待ち", "CI が走っている: " + "、".join(running[:2]), "終わるのを待つ")
    if pr.get("isDraft"):
        return turn("自分の番", "Draft のまま", "Ready にする")
    if pushed:
        return turn("レビュー待ち", f"{'、'.join(pushed)} の再レビュー待ち", "待つ")
    if any(r.get("state") == "APPROVED" for r in reviewers(pr, me).values()):
        return turn("自分の番", "承認された", "マージする")
    return turn("レビュー待ち", "レビュー待ち", "待つ")


def badges(pr: dict | None, closed: dict | None, path: str | None) -> list[str]:
    out = []
    if pr and pr.get("isDraft"):
        out.append("Draft")
    if not pr and not closed:
        out.append("PR なし")
    if not path:
        out.append("worktree なし")
    return out


def build_items(worktrees: dict[str, str], prs: list[dict], closed: dict[str, dict], me: str) -> list[dict]:
    """カードの一覧。worktrees はブランチ名 → パス、closed はブランチ名 → 閉じた PR。worktree の無い開いた PR も 1 枚にする。"""
    open_by_branch = {p["headRefName"]: p for p in prs}
    rows = [(Path(path).name, path, branch) for branch, path in worktrees.items()]
    rows += [(f"pr-{p['number']}", None, b) for b, p in open_by_branch.items() if b not in worktrees]
    items = []
    for name, path, branch in rows:
        pr = open_by_branch.get(branch)
        done = None if pr else closed.get(branch)
        shown = pr or done or {}
        items.append({
            **judge(pr, done, me),
            "id": name, "label": name if path else f"PR #{shown['number']}", "path": path, "branch": branch,
            "title": shown.get("title") or branch,
            "pr": shown.get("number"), "url": shown.get("url"), "updated_at": (pr or {}).get("updatedAt"),
            "badges": badges(pr, done, path),
        })
    # 同じ状態の中では、長く動いていないものを上に（動きの無い PR ほど気付きたい）。PR の無いものは最後
    items.sort(key=lambda i: (STATES.index(i["state"]), i["updated_at"] is None, i["updated_at"] or ""))
    return items
