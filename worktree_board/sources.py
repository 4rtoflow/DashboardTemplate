"""git と gh から材料を取る。読むだけで、GitHub への発信はしない。"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

FIELDS = ("number,title,url,headRefName,headRefOid,baseRefName,isDraft,mergeable,"
          "reviews,reviewRequests,statusCheckRollup,updatedAt")
CLOSED_FIELDS = "number,headRefName,state,title,url,mergedAt,closedAt"


class FetchError(Exception):
    pass


def run(cmd: list[str], cwd: Path) -> str:
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=120)
    except FileNotFoundError:
        raise FetchError(f"{cmd[0]} が見つからない（インストールして PATH に通す）") from None
    except subprocess.TimeoutExpired:
        raise FetchError(f"{' '.join(cmd[:3])} が時間内に終わらなかった") from None
    if r.returncode != 0:
        raise FetchError(r.stderr.strip()[:300] or f"{' '.join(cmd[:3])} が失敗した")
    return r.stdout


def parse_worktrees(porcelain: str) -> tuple[str | None, dict[str, str]]:
    """`git worktree list --porcelain` の出力から、primary checkout のパスと、ブランチ名 → パス。
    先頭が primary checkout。ブランチを持たない（detached・bare）worktree は数えない。"""
    primary, out, path = None, {}, None
    for line in porcelain.splitlines():
        if line.startswith("worktree "):
            path = line[9:]
            primary = primary or path
        elif line.startswith("branch refs/heads/") and path:
            out[line[18:]] = path
    return primary, out


class Source:
    """1 つの repo の材料の取り方。checkout はその repo のどこでもよい（worktree の中でも、primary checkout でも）。"""

    def __init__(self, checkout: Path, repo: str | None = None):
        self.checkout, self.repo, self.me = checkout, repo, None

    def gh(self, *args: str) -> str:
        return run(["gh", *args], self.checkout)

    def fetch(self) -> dict:
        """worktrees（ブランチ名 → パス）・prs（開いている自分の PR）・closed（ブランチ名 → 閉じた自分の PR）・me を返す。"""
        self.repo = self.repo or self.gh("repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner").strip()
        self.me = self.me or self.gh("api", "user", "--jq", ".login").strip()
        primary, branches = parse_worktrees(run(["git", "worktree", "list", "--porcelain"], self.checkout))
        worktrees = {b: p for b, p in branches.items() if p != primary}  # primary checkout は作業の場ではないので出さない
        prs = json.loads(self.gh("pr", "list", "--repo", self.repo, "--author", "@me", "--state", "open",
                                 "--limit", "100", "--json", FIELDS))
        rows = json.loads(self.gh("pr", "list", "--repo", self.repo, "--author", "@me", "--state", "closed",
                                  "--limit", "100", "--json", CLOSED_FIELDS))
        closed = {r["headRefName"]: r for r in sorted(rows, key=lambda r: r["number"])}  # 同じブランチは新しいほう
        return {"worktrees": worktrees, "prs": prs, "closed": closed, "me": self.me}
