"""Turn a feed into an HTML page."""

import re
from datetime import UTC, datetime
from html import escape
from pathlib import Path
from urllib.parse import urlsplit

from rss_reader_try.feed import Feed

LINK_SCHEMES = frozenset({"http", "https"})
MAX_FILENAME_LENGTH = 100


def format_time(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y/%m/%d %H:%M UTC")


def _link(url: str, text: str) -> str:
    if urlsplit(url).scheme.lower() not in LINK_SCHEMES:
        return escape(text)
    return f'<a href="{escape(url)}" rel="noopener noreferrer">{escape(text)}</a>'


def render_html(feed: Feed) -> str:
    items = "\n".join(
        f"<li>{article.date or '----/--/--'} -- {_link(article.url, article.title)}</li>"
        for article in feed.articles
    )
    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'">
<title>自作PythonRSS</title>
<style>div {{ margin: 20px; background-color: khaki; padding: 10px; }}</style>
</head>
<body>
<div>
<h3>Articles of site: {_link(feed.site_url, feed.title)}</h3>
<ul>
{items}
</ul>
<h4>This RSS was made at {format_time(feed.fetched_at)}</h4>
</div>
</body>
</html>
"""


def output_filename(title: str) -> str:
    """Make a safe file name (no path separators, no dots) from a feed title."""
    stem = re.sub(r"[^\w]+", "-", title).strip("-")[:MAX_FILENAME_LENGTH].strip("-")
    return f"{stem or 'feed'}.html"


def write_html(feed: Feed, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / output_filename(feed.title)
    path.write_text(render_html(feed), encoding="utf-8")
    return path
