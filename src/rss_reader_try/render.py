"""Turn feeds into HTML pages."""

import re
from collections.abc import Collection, Sequence
from datetime import UTC, datetime
from html import escape
from urllib.parse import quote, urlsplit

from rss_reader_try.feed import Feed

LINK_SCHEMES = frozenset({"http", "https"})
MAX_FILENAME_LENGTH = 100


def format_time(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y/%m/%d %H:%M UTC")


def plural(count: int, noun: str) -> str:
    return f"{count} {noun}{'' if count == 1 else 's'}"


def _link(url: str, text: str) -> str:
    if urlsplit(url).scheme.lower() not in LINK_SCHEMES:
        return escape(text)
    return f'<a href="{escape(url)}" rel="noopener noreferrer">{escape(text)}</a>'


def _page(body: str) -> str:
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
{body}
</div>
</body>
</html>
"""


def render_html(feed: Feed) -> str:
    items = "\n".join(
        f"<li>{article.date or '----/--/--'} -- {'<strong>NEW</strong> ' if article.new else ''}"
        f"{_link(article.url, article.title)}</li>"
        for article in feed.articles
    )
    return _page(f"""<h3>Articles of site: {_link(feed.site_url, feed.title)}</h3>
<ul>
{items}
</ul>
<h4>This RSS was made at {format_time(feed.fetched_at)}</h4>""")


def _new_count(feed: Feed) -> str:
    new = sum(article.new for article in feed.articles)
    return f", {new} new" if new else ""


def render_index(pages: Sequence[tuple[Feed, str]], now: datetime) -> str:
    """Link to each (feed, file name) page."""
    items = "\n".join(
        f'<li><a href="{escape(quote(name))}">{escape(feed.title)}</a>'
        f" -- {plural(len(feed.articles), 'article')}{_new_count(feed)}"
        f" (fetched {format_time(feed.fetched_at)})</li>"
        for feed, name in pages
    )
    return _page(f"""<h3>Feeds</h3>
<ul>
{items}
</ul>
<h4>This index was made at {format_time(now)}</h4>""")


def output_filename(title: str, taken: Collection[str] = ()) -> str:
    """Make a safe file name (no path separators, no dots) that is not in `taken`."""
    stem = re.sub(r"[^\w]+", "-", title).strip("-")[:MAX_FILENAME_LENGTH].strip("-") or "feed"
    lowered = {name.lower() for name in taken}
    name, number = f"{stem}.html", 1
    while name.lower() in lowered:
        number += 1
        name = f"{stem}-{number}.html"
    return name
