import json
import sqlite3
from contextlib import closing
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from rss_reader_try.feed import Article, Feed
from rss_reader_try.store import load, save

FEED = Feed(
    source="https://example.com/feed.xml",
    title="Example",
    site_url="https://example.com/",
    fetched_at=datetime(2026, 10, 13, 7, 15, tzinfo=UTC),
    articles=(
        Article(title="first", url="https://example.com/1", date="2016/04/03"),
        Article(title="no date", url="", date=None),
    ),
)

# The table created by the original 2017 version of this app.
ORIGINAL_SCHEMA = """CREATE TABLE "rss_data" (
    `id` INTEGER NOT NULL UNIQUE,
    `siteTitle` TEXT,
    `siteUrl` TEXT,
    `createTime` TEXT,
    `jsonData` TEXT,
    `rssUrl` TEXT,
    PRIMARY KEY(id)
)"""


def count_rows(db: Path) -> int:
    with closing(sqlite3.connect(db)) as connection:
        return connection.execute("SELECT COUNT(*) FROM rss_data").fetchone()[0]


def test_load_from_new_database(tmp_path: Path) -> None:
    db = tmp_path / "new.sqlite3"

    assert load(db, FEED.source) is None
    assert db.exists()


def test_save_and_load(tmp_path: Path) -> None:
    db = tmp_path / "cache.sqlite3"

    save(db, FEED)

    assert load(db, FEED.source) == FEED
    assert load(db, "https://other.example.com/feed.xml") is None


def test_save_replaces_previous_row(tmp_path: Path) -> None:
    db = tmp_path / "cache.sqlite3"
    newer = Feed(
        source=FEED.source,
        title="Renamed",
        site_url=FEED.site_url,
        fetched_at=datetime(2026, 10, 14, tzinfo=UTC),
        articles=(),
    )

    save(db, FEED)
    save(db, newer)

    assert load(db, FEED.source) == newer
    assert count_rows(db) == 1


def test_rows_from_original_version_are_treated_as_missing(tmp_path: Path) -> None:
    db = tmp_path / "old.sqlite3"
    legacy = {
        "siteTitle": "Example",
        "siteUrl": "https://example.com/",
        "rssUrl": FEED.source,
        "createTime": "201604041015",
        "articleNum": 1,
        "article0": {"title": "old", "url": "https://example.com/0", "date": "2016/04/03"},
    }
    with sqlite3.connect(db) as connection:
        connection.execute(ORIGINAL_SCHEMA)
        connection.execute(
            "INSERT INTO rss_data (siteTitle, siteUrl, createTime, jsonData, rssUrl)"
            " VALUES (?, ?, ?, ?, ?)",
            ("Example", "https://example.com/", "201604041015", json.dumps(legacy), FEED.source),
        )
    connection.close()

    assert load(db, FEED.source) is None

    save(db, FEED)

    assert load(db, FEED.source) == FEED
    assert count_rows(db) == 1


def test_broken_json_is_treated_as_missing(tmp_path: Path) -> None:
    db = tmp_path / "broken.sqlite3"
    save(db, FEED)
    with sqlite3.connect(db) as connection:
        connection.execute("UPDATE rss_data SET jsonData = '{not json'")
    connection.close()

    assert load(db, FEED.source) is None


def test_save_and_load_validators(tmp_path: Path) -> None:
    db = tmp_path / "cache.sqlite3"
    feed = replace(FEED, etag='"v1"', last_modified="Sun, 03 Apr 2016 12:00:00 GMT")

    save(db, feed)

    assert load(db, FEED.source) == feed
