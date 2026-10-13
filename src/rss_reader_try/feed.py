"""Read a feed from a URL or a local file and turn it into plain data."""

import time
from dataclasses import dataclass
from datetime import datetime
from email.message import Message
from http.client import HTTPException
from pathlib import Path
from typing import IO, override
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

import feedparser

USER_AGENT = "rss-reader-try/2.0 (+https://github.com/yuu-eguci/rss-reader-try)"
TIMEOUT_SECONDS = 30.0
MAX_BYTES = 10 * 1024 * 1024
HTTP_SCHEMES = frozenset({"http", "https"})


class FeedError(Exception):
    """The feed could not be read."""


@dataclass(frozen=True)
class Article:
    title: str
    url: str
    date: str | None  # "YYYY/MM/DD"


@dataclass(frozen=True)
class Feed:
    source: str
    title: str
    site_url: str
    fetched_at: datetime
    articles: tuple[Article, ...]


class _HttpOnlyRedirectHandler(HTTPRedirectHandler):
    @override
    def redirect_request(
        self,
        req: Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: Message,
        newurl: str,
    ) -> Request | None:
        if urlsplit(newurl).scheme not in HTTP_SCHEMES:
            fp.close()
            raise URLError(f"refusing redirect to {newurl}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def read_source(
    source: str, *, timeout: float = TIMEOUT_SECONDS, max_bytes: int = MAX_BYTES
) -> bytes:
    """Return the raw bytes of an http(s) URL or a local file."""
    try:
        scheme = urlsplit(source).scheme
        if scheme in HTTP_SCHEMES:
            opener = build_opener(_HttpOnlyRedirectHandler)
            request = Request(source, headers={"User-Agent": USER_AGENT})  # noqa: S310 - scheme checked
            with opener.open(request, timeout=timeout) as response:
                data = response.read(max_bytes + 1)
                if len(data) <= max_bytes and response.length:
                    raise HTTPException("connection closed before the end of the response")
        elif not scheme:
            with Path(source).open("rb") as file:
                data = file.read(max_bytes + 1)
        else:
            raise FeedError(f"unsupported feed source: {source} (use http(s) or a file path)")
    except HTTPError as error:
        error.close()
        raise FeedError(f"cannot read {source}: {error}") from error
    except (OSError, HTTPException, ValueError) as error:
        detail = getattr(error, "reason", error)
        raise FeedError(f"cannot read {source}: {detail}") from error
    if len(data) > max_bytes:
        raise FeedError(f"{source} is larger than {max_bytes} bytes")
    return data


def _format_date(parsed: time.struct_time | None) -> str | None:
    if parsed is None:
        return None
    return f"{parsed.tm_year:04d}/{parsed.tm_mon:02d}/{parsed.tm_mday:02d}"


def fetch(source: str, now: datetime) -> Feed:
    """Read and parse the feed at `source`."""
    data = read_source(source)
    headers = {"content-location": source} if urlsplit(source).scheme in HTTP_SCHEMES else {}
    parsed = feedparser.parse(data, response_headers=headers)
    if not parsed.get("version") and not parsed.entries:
        raise FeedError(f"not a feed: {source}")
    return Feed(
        source=source,
        title=parsed.feed.get("title") or source,
        site_url=parsed.feed.get("link", ""),
        fetched_at=now,
        articles=tuple(
            Article(
                title=entry.get("title") or "(no title)",
                url=entry.get("link", ""),
                date=_format_date(entry.get("published_parsed") or entry.get("updated_parsed")),
            )
            for entry in parsed.entries
        ),
    )
