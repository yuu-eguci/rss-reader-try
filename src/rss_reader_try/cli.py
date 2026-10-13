"""Command line entry point."""

import argparse
import sqlite3
import sys
import webbrowser
from datetime import UTC, datetime, timedelta
from pathlib import Path

from rss_reader_try import store
from rss_reader_try.feed import Feed, FeedError, fetch
from rss_reader_try.render import (
    format_time,
    output_filename,
    plural,
    render_html,
    render_index,
)

INDEX = "index.html"


def _hours(value: str) -> timedelta:
    try:
        hours = float(value)
    except ValueError:
        hours = -1.0
    if not hours >= 0:
        raise argparse.ArgumentTypeError(f"must be a number of hours >= 0: {value!r}")
    return timedelta(hours=hours)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rss-reader-try",
        description="Read RSS / Atom feeds, cache them in SQLite and write the articles as HTML.",
    )
    parser.add_argument(
        "feeds", nargs="+", metavar="FEED", help="feed URL (http/https) or local file path"
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
    return parser


def is_fresh(fetched_at: datetime, now: datetime, max_age: timedelta) -> bool:
    return now - fetched_at < max_age


def _get_feed(args: argparse.Namespace, source: str, now: datetime) -> tuple[Feed, bool]:
    """Return the feed and whether it came from the cache."""
    cached = store.load(args.db, source)
    if cached is not None and is_fresh(cached.fetched_at, now, args.max_age):
        return cached, True
    try:
        feed = fetch(source, now)
    except FeedError as error:
        if cached is None:
            raise
        print(f"warning: {error}; using the cached copy", file=sys.stderr)
        return cached, True
    store.save(args.db, feed)
    return feed, False


def _write(path: Path, html: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    return path


def run(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    now = datetime.now(UTC)
    pages: list[tuple[Feed, str]] = []
    failed = False
    sources = list(dict.fromkeys(args.feeds))
    for source in sources:
        try:
            feed, from_cache = _get_feed(args, source, now)
            name = output_filename(feed.title, {INDEX, *(name for _, name in pages)})
            path = _write(args.out / name, render_html(feed))
        except sqlite3.Error as error:
            print(f"error: {args.db}: {error}", file=sys.stderr)
            failed = True
            continue
        except (FeedError, OSError) as error:
            print(f"error: {error}", file=sys.stderr)
            failed = True
            continue
        pages.append((feed, name))
        summary = f'{plural(len(feed.articles), "article")} from "{feed.title}"'
        if from_cache:
            print(f"cache: {summary} (fetched {format_time(feed.fetched_at)}) -> {path}")
        else:
            print(f"fetched: {summary} -> {path}")

    if not pages:
        return 1
    target = args.out / pages[0][1]
    if len(sources) > 1:
        try:
            target = _write(args.out / INDEX, render_index(pages, now))
        except OSError as error:
            print(f"error: {error}", file=sys.stderr)
            return 1
        print(f"index: {plural(len(pages), 'page')} -> {target}")
    if args.open and not webbrowser.open(target.resolve().as_uri()):
        print("warning: could not open a browser", file=sys.stderr)
    return 1 if failed else 0


def main() -> None:
    sys.exit(run())
