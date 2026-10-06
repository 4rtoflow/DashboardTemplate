# dashboard-template

自分の git worktree と GitHub の PR を見て、「今ボールを持っているのは誰か」をブラウザの Dashboard に出す小さな道具。
見るだけで、GitHub への書き込み（コメント・ラベル・マージなど）は一切しない。

```
自分の番   │ GitHub 待ち │ レビュー待ち │ 完了
```

## 要るもの

- Python 3.9 以上（標準ライブラリだけ。インストールするものは無い）
- `git`
- [GitHub CLI](https://cli.github.com/)（`gh`）。`gh auth login` で入っておく

## 使い方

このリポジトリを clone したフォルダで動かし、見たい repo は `--checkout` で渡す。

```bash
cd dashboard-template
python3 -m worktree_board serve --checkout ~/work/my-repo   # http://localhost:8765 に Dashboard を出す
python3 -m worktree_board status --checkout ~/work/my-repo   # 今の状態を 1 回だけ端末に出す
```

| オプション | 意味 |
|---|---|
| `--checkout PATH` | 見る repo のフォルダ。省略すると今のフォルダ |
| `--repo OWNER/REPO` | 省略すると、`gh` が `checkout` の remote から決める |
| `--port N` | `serve` の待ち受けポート（既定 8765） |
| `--interval N` | `serve` が見直す間隔の秒数（既定 60） |

Dashboard の「今すぐ見直す」で、次の回を待たずに見直せる。止めるのは Ctrl-C。

## 何を見ているか

- worktree: `git worktree list` のうち、primary checkout 以外（ブランチを持つもの）
- PR: その repo の、自分が作った PR（開いているもの・閉じたもの）。worktree の無い開いた PR も 1 枚になる

worktree のブランチと PR のブランチを突き合わせて、1 つの worktree を 1 枚のカードにする。

## 状態の決め方

上から順に当てはめ、先に当たったものが勝つ（`worktree_board/judge.py`）。

| 順 | 条件 | 状態 | 次にすること |
|---|---|---|---|
| 1 | PR が閉じている（開いた PR が無い） | 完了 | worktree を片付ける |
| 2 | PR がまだ無い | 自分の番 | 作業を進めるか、PR を作る |
| 3 | ベースブランチとコンフリクトしている | 自分の番 | 取り込んで解く |
| 4 | CI が失敗している（同じチェックは最新の run だけ見る） | 自分の番 | 直して push する |
| 5 | 今の commit に対して変更が求められている | 自分の番 | 指摘を直して push する |
| 6 | CI が走っている | GitHub 待ち | 待つ |
| 7 | Draft のまま | 自分の番 | Ready にする |
| 8 | 変更を求められた後に push した（再レビュー待ち） | レビュー待ち | 待つ |
| 9 | 承認されている | 自分の番 | マージする |
| 10 | それ以外 | レビュー待ち | 待つ |

同じ列の中では、PR が長く動いていないものを上に出す。

## 安全について

- `127.0.0.1` だけで待ち受ける。`localhost` 以外の名前で来た要求は断る。
- 書き込みの API（見直しの依頼）は、独自ヘッダーが無ければ断る（ほかのサイトのページから勝手に押されないため）。
- 記録は何も保存しない（ファイルを作らない）。

## テスト

```bash
python3 -m unittest discover -s tests -t .
```

## 構成

| ファイル | 役割 |
|---|---|
| `worktree_board/judge.py` | 状態の判定（副作用なし） |
| `worktree_board/sources.py` | `git` と `gh` から材料を取る |
| `worktree_board/server.py` | 定期的な見直しと、Dashboard・API を出す HTTP サーバー |
| `worktree_board/dashboard.html` | 画面 |
| `worktree_board/__main__.py` | コマンド（`serve`・`status`） |
| `tests/test_judge.py` | 判定の順・境界・サーバーの防御のテスト |

## API

| | |
|---|---|
| `GET /` | Dashboard |
| `GET /api/worktrees` | カードの一覧（JSON） |
| `POST /api/refresh` | 次の回を待たずに見直す（`X-Dashboard: 1` ヘッダーが要る） |
