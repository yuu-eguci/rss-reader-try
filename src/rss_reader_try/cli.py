"""Command line entry point."""

import argparse
import sqlite3
import sys
import webbrowser
from datetime import UTC, datetime, timedelta
from pathlib import Path

from rss_reader_try import store
from rss_reader_try.feed import FeedError, fetch
from rss_reader_try.render import format_time, write_html


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
        description="Read an RSS / Atom feed, cache it in SQLite and write the articles as HTML.",
    )
    parser.add_argument("feed", metavar="FEED", help="feed URL (http/https) or local file path")
    parser.add_argument("--db", type=Path, default=Path("my_rss.sqlite3"), help="cache database")
    parser.add_argument("--out", type=Path, default=Path("html"), help="output directory")
    parser.add_argument(
        "--max-age",
        type=_hours,
        default=timedelta(hours=6),
        metavar="HOURS",
        help="use the cache if it is younger than this (default: 6, 0 = always fetch)",
    )
    parser.add_argument("--open", action="store_true", help="open the HTML in a web browser")
    return parser


def is_fresh(fetched_at: datetime, now: datetime, max_age: timedelta) -> bool:
    return now - fetched_at < max_age


def run(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    now = datetime.now(UTC)
    try:
        feed = store.load(args.db, args.feed)
        from_cache = feed is not None and is_fresh(feed.fetched_at, now, args.max_age)
        if not from_cache:
            feed = fetch(args.feed, now)
            store.save(args.db, feed)
        path = write_html(feed, args.out)
    except sqlite3.Error as error:
        print(f"error: {args.db}: {error}", file=sys.stderr)
        return 1
    except (FeedError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    count = len(feed.articles)
    summary = f'{count} article{"" if count == 1 else "s"} from "{feed.title}"'
    if from_cache:
        print(f"cache: {summary} (fetched {format_time(feed.fetched_at)}) -> {path}")
    else:
        print(f"fetched: {summary} -> {path}")
    if args.open and not webbrowser.open(path.resolve().as_uri()):
        print("warning: could not open a browser", file=sys.stderr)
    return 0


def main() -> None:
    sys.exit(run())
