"""Cache feeds in SQLite."""

import json
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

from rss_reader_try.feed import Article, Feed

# Same table as the original version of this app, so its databases keep working.
SCHEMA = """CREATE TABLE IF NOT EXISTS rss_data (
    id INTEGER NOT NULL UNIQUE,
    siteTitle TEXT,
    siteUrl TEXT,
    createTime TEXT,
    jsonData TEXT,
    rssUrl TEXT,
    PRIMARY KEY(id)
)"""
FORMAT = 2


def _connect(db: Path) -> sqlite3.Connection:
    db.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db)
    try:
        connection.execute(SCHEMA)
    except sqlite3.Error:
        connection.close()
        raise
    return connection


def load(db: Path, source: str) -> Feed | None:
    """Return the cached feed, or None if there is no usable cache."""
    with closing(_connect(db)) as connection:
        row = connection.execute(
            "SELECT jsonData FROM rss_data WHERE rssUrl = ? ORDER BY id DESC LIMIT 1", (source,)
        ).fetchone()
    if row is None:
        return None
    try:
        data = json.loads(row[0])
        if data["format"] != FORMAT:
            return None
        return Feed(
            source=data["source"],
            title=data["title"],
            site_url=data["siteUrl"],
            fetched_at=datetime.fromisoformat(data["fetchedAt"]),
            articles=tuple(Article(**article) for article in data["articles"]),
            etag=data.get("etag"),
            last_modified=data.get("lastModified"),
        )
    except ValueError, KeyError, TypeError:
        # Rows written by the original version (or broken ones) are simply fetched again.
        return None


def save(db: Path, feed: Feed) -> None:
    """Store `feed`, replacing any previous cache for the same source."""
    data = {
        "format": FORMAT,
        "source": feed.source,
        "title": feed.title,
        "siteUrl": feed.site_url,
        "fetchedAt": feed.fetched_at.isoformat(),
        "articles": [{"title": a.title, "url": a.url, "date": a.date} for a in feed.articles],
        "etag": feed.etag,
        "lastModified": feed.last_modified,
    }
    with closing(_connect(db)) as connection, connection:
        connection.execute("DELETE FROM rss_data WHERE rssUrl = ?", (feed.source,))
        connection.execute(
            "INSERT INTO rss_data (siteTitle, siteUrl, createTime, jsonData, rssUrl)"
            " VALUES (?, ?, ?, ?, ?)",
            (
                feed.title,
                feed.site_url,
                feed.fetched_at.isoformat(),
                json.dumps(data, ensure_ascii=False),
                feed.source,
            ),
        )
