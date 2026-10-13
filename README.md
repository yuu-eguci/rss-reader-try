RssReaderTry
===

Rssリーダを作ってみる。DB接続とか feedparser とか webbrowser とか。

フィード (RSS / Atom) を読んで記事一覧の HTML を書き出す CLI。読んだ内容は SQLite にキャッシュして、6 時間以内ならネットに行かずキャッシュから作る。

- Docker: 対応!
- Python: 3.15!
- Linter: Ruff!
- Test: pytest!
- feedparser: 6.0!

## パッと実行してみたい

```bash
docker build -t rss-reader-try .

# 同梱のサンプルフィード (ネット不要) を読んで ./html/ に HTML を書き出す
docker run --rm --user "$(id -u):$(id -g)" -v "$PWD:/data" rss-reader-try examples/sample-feed.xml
# fetched: 3 articles from "Sample Feed" -> html/Sample-Feed.html

# もう一度実行すると、6 時間以内なのでキャッシュ (./my_rss.sqlite3) から作る
docker run --rm --user "$(id -u):$(id -g)" -v "$PWD:/data" rss-reader-try examples/sample-feed.xml
# cache: 3 articles from "Sample Feed" (fetched 2026/10/13 07:15 UTC) -> html/Sample-Feed.html

# 本物のフィードも読める
docker run --rm --user "$(id -u):$(id -g)" -v "$PWD:/data" rss-reader-try https://qiita.com/mpyw/feed.atom
```

`html/Sample-Feed.html` をブラウザで開くと、こんな感じの記事一覧が見える。

![1](media/RSSREADER.jpg)

## 使い方

```
rss-reader-try [-h] [--db DB] [--out OUT] [--max-age HOURS] [--open] FEED
```

| 引数 | 既定値 | 説明 |
| --- | --- | --- |
| `FEED` | (必須) | フィードの URL (`http://` / `https://`) かローカルファイルのパス |
| `--db` | `my_rss.sqlite3` | キャッシュ用 SQLite ファイル。なければ作る |
| `--out` | `html` | HTML の出力先ディレクトリ。なければ作る |
| `--max-age` | `6` | キャッシュの有効期間 (時間)。`0` なら毎回取りに行く |
| `--open` | なし | 書き出した HTML をブラウザで開く (Docker の外で動かすとき用) |

- 成功すると `fetched:` (取りに行った) か `cache:` (キャッシュから作った) で始まる 1 行を出して終了コード 0。
- フィードが読めない (ファイルがない、HTTP エラー、フィードじゃない、など) ときは `error:` で始まるメッセージを標準エラーに出して終了コード 1。
- 引数がおかしい (`--max-age -1` など) ときは使い方を出して終了コード 2。
- 出力ファイル名はフィードのタイトルから作る (記号は `-` に置き換え)。

Docker を使わないなら [uv](https://docs.astral.sh/uv/) で。

```bash
uv run rss-reader-try --open examples/sample-feed.xml
```

## 開発

```bash
# lint (Ruff) とテスト (pytest) を Docker で回す
docker build --target dev -t rss-reader-try:dev .
docker run --rm rss-reader-try:dev
```

CI (GitHub Actions) でも同じものを回している。

## セキュリティまわり

- フィードの中身は HTML エスケープしてから埋め込む。リンクは `http` / `https` だけ有効にする。
- HTML には Content-Security-Policy を付けてスクリプトを動かさない。
- 出力ファイル名に `/` や `..` が入らないようにしている。
- フィードの取得にはタイムアウト (30 秒) とサイズ上限 (10 MB) がある。リダイレクトは `http` / `https` だけ追う。
- Docker イメージは root ではないユーザで動く。
