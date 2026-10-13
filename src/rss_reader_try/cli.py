"""Command line entry point."""

import argparse
import sqlite3
import sys
import webbrowser
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from rss_reader_try import store
from rss_reader_try.feed import Feed, FeedError, NotModified, fetch
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
        if hours >= 0:
            return timedelta(hours=hours)
    except ValueError, OverflowError:
        pass
    raise argparse.ArgumentTypeError(f"must be a number of hours >= 0: {value!r}")


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


def _get_feed(args: argparse.Namespace, source: str, now: datetime) -> tuple[Feed, str]:
    """Return the feed and where it came from: "cache", "fetched" or "not modified"."""
    cached = store.load(args.db, source)
    if cached is None:
        feed, origin = fetch(source, now), "fetched"
    elif is_fresh(cached.fetched_at, now, args.max_age):
        return cached, "cache"
    else:
        try:
            feed, origin = fetch(source, now, cached), "fetched"
        except NotModified:
            feed, origin = replace(cached, fetched_at=now), "not modified"
        except FeedError as error:
            print(f"warning: {error}; using the cached copy", file=sys.stderr)
            return cached, "cache"
    store.save(args.db, feed)
    return feed, origin


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
            feed, origin = _get_feed(args, source, now)
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
        if origin == "cache":
            print(f"cache: {summary} (fetched {format_time(feed.fetched_at)}) -> {path}")
        elif origin == "not modified":
            print(f"fetched: {summary} (not modified) -> {path}")
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
