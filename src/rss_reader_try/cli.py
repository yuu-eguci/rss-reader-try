"""Command line entry point."""

import argparse
import re
import sqlite3
import sys
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from importlib.metadata import version
from pathlib import Path
from typing import Literal
from xml.etree import ElementTree

from rss_reader_try import store
from rss_reader_try.feed import Feed, FeedError, NotModified, fetch, mark_new
from rss_reader_try.opml import read_opml
from rss_reader_try.render import (
    format_time,
    output_filename,
    plural,
    render_html,
    render_index,
)

PROG = "rss-reader-try"
INDEX = "index.html"
MAX_PARALLEL_FETCHES = 4
type Origin = Literal["cache", "fetched", "updated", "not modified"]
# C0/C1 controls and bidi overrides: feed text must not drive the terminal.
UNSAFE_FOR_TERMINAL = re.compile("[\x00-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]")


def _hours(value: str) -> timedelta:
    try:
        hours = float(value)
        if hours >= 0:
            return timedelta(hours=hours)
    except ValueError, OverflowError:
        pass
    raise argparse.ArgumentTypeError(f"must be a number of hours >= 0: {value!r}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Read RSS / Atom feeds, cache them in SQLite and write the articles as HTML.",
    )
    parser.add_argument(
        "feeds", nargs="*", metavar="FEED", help="feed URL (http/https) or local file path"
    )
    parser.add_argument(
        "--opml",
        type=Path,
        action="append",
        default=[],
        metavar="FILE",
        help="also read the feeds listed in this OPML file (repeatable)",
    )
    parser.add_argument("--db", type=Path, default=Path("my_rss.sqlite3"), help="cache database")
    parser.add_argument("--out", type=Path, default=Path("html"), help="output directory")
    parser.add_argument(
        "--max-age",
        type=_hours,
        default=timedelta(hours=6),
        metavar="HOURS",
        help="use the cache if it is younger than this (default: 6, 0 = always fetch)",
    )
    parser.add_argument(
        "--open", action="store_true", help="open the HTML (the index for 2+ feeds) in a browser"
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {version(PROG)}")
    return parser


def is_fresh(fetched_at: datetime, now: datetime, max_age: timedelta) -> bool:
    return now - fetched_at < max_age


def _fetch(source: str, now: datetime, cached: Feed | None) -> Feed | FeedError | NotModified:
    """Run in a worker thread: fetch, returning the failure instead of raising it."""
    try:
        return fetch(source, now, cached)
    except (FeedError, NotModified) as error:
        return error


def _resolve(
    cached: Feed | None, fetched: Feed | FeedError | NotModified, now: datetime
) -> tuple[Feed, Origin]:
    """Combine the stale (or missing) cache and the fetch result into the feed to show."""
    if isinstance(fetched, Feed):
        if cached is None:
            return fetched, "fetched"
        return mark_new(fetched, cached), "updated"
    if cached is None:
        raise fetched  # a FeedError: NotModified needs the validators of a cached copy
    if isinstance(fetched, NotModified):
        articles = tuple(replace(article, new=False) for article in cached.articles)
        return replace(cached, fetched_at=now, articles=articles), "not modified"
    _say(f"warning: {fetched}; using the cached copy", error=True)
    return cached, "cache"


def _say(message: str, *, error: bool = False) -> None:
    print(UNSAFE_FOR_TERMINAL.sub("?", message), file=sys.stderr if error else sys.stdout)


def _write(path: Path, html: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    return path


def _report(feed: Feed, origin: Origin, path: Path) -> None:
    summary = f'{plural(len(feed.articles), "article")} from "{feed.title}"'
    if origin == "cache":
        _say(f"cache: {summary} (fetched {format_time(feed.fetched_at)}) -> {path}")
    elif origin == "not modified":
        _say(f"fetched: {summary} (not modified) -> {path}")
    elif origin == "updated":
        new = sum(article.new for article in feed.articles)
        _say(f"fetched: {summary} ({new} new) -> {path}")
    else:
        _say(f"fetched: {summary} -> {path}")


def _read_feeds(
    args: argparse.Namespace, sources: list[str], now: datetime
) -> tuple[list[tuple[Feed, str]], bool]:
    """Write a page for each feed; return the (feed, file name) pages and whether any failed."""
    try:
        caches = {source: store.load(args.db, source) for source in sources}
    except sqlite3.Error as error:
        _say(f"error: {args.db}: {error}", error=True)
        return [], True
    fresh = {
        source: cached
        for source, cached in caches.items()
        if cached is not None and is_fresh(cached.fetched_at, now, args.max_age)
    }
    stale = [source for source in sources if source not in fresh]
    with ThreadPoolExecutor(MAX_PARALLEL_FETCHES) as pool:
        results = dict(
            zip(stale, pool.map(lambda s: _fetch(s, now, caches[s]), stale), strict=True)
        )

    pages: list[tuple[Feed, str]] = []
    failed = False
    for source in sources:
        origin: Origin
        try:
            if source in fresh:
                feed, origin = fresh[source], "cache"
            else:
                feed, origin = _resolve(caches[source], results[source], now)
                if origin != "cache":
                    store.save(args.db, feed)
            name = output_filename(feed.title, {INDEX, *(name for _, name in pages)})
            path = _write(args.out / name, render_html(feed))
        except sqlite3.Error as error:
            _say(f"error: {args.db}: {error}", error=True)
            failed = True
            continue
        except (FeedError, OSError) as error:
            _say(f"error: {error}", error=True)
            failed = True
            continue
        pages.append((feed, name))
        _report(feed, origin, path)

    return pages, failed


def run(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    sources = list(args.feeds)
    for opml in args.opml:
        try:
            sources += read_opml(opml)
        except (OSError, ElementTree.ParseError, ValueError) as error:
            _say(f"error: {opml}: {error}", error=True)
            return 1
    sources = list(dict.fromkeys(sources))
    if not sources:
        parser.error("no feeds given (pass FEED or --opml)")

    now = datetime.now(UTC)
    pages, failed = _read_feeds(args, sources, now)
    if not pages:
        return 1
    target = args.out / pages[0][1]
    if len(sources) > 1:
        try:
            target = _write(args.out / INDEX, render_index(pages, now))
        except OSError as error:
            _say(f"error: {error}", error=True)
            return 1
        _say(f"index: {plural(len(pages), 'page')} -> {target}")
    if args.open and not webbrowser.open(target.resolve().as_uri()):
        _say("warning: could not open a browser", error=True)
    return 1 if failed else 0


def main() -> None:
    sys.exit(run())
