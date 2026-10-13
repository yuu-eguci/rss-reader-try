"""Read a feed from a URL or a local file and turn it into plain data."""

import socket
import time
from dataclasses import dataclass, replace
from datetime import datetime
from email.message import Message
from http import HTTPStatus
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
    etag: str | None = None
    last_modified: str | None = None


@dataclass(frozen=True)
class Download:
    data: bytes | None  # None: not modified since the validators that were sent
    etag: str | None = None
    last_modified: str | None = None
    content_type: str | None = None  # may carry the charset


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
    source: str,
    *,
    etag: str | None = None,
    last_modified: str | None = None,
    timeout: float = TIMEOUT_SECONDS,
    max_bytes: int = MAX_BYTES,
) -> Download:
    """Read an http(s) URL (conditionally, if validators are given) or a local file."""
    validators = Download(None)
    try:
        scheme = urlsplit(source).scheme
        if scheme in HTTP_SCHEMES:
            headers = {"User-Agent": USER_AGENT}
            if etag:
                headers["If-None-Match"] = etag
            if last_modified:
                headers["If-Modified-Since"] = last_modified
            opener = build_opener(_HttpOnlyRedirectHandler)
            request = Request(source, headers=headers)  # noqa: S310 - scheme checked
            with opener.open(request, timeout=timeout) as response:
                data = response.read(max_bytes + 1)
                if len(data) <= max_bytes and response.length:
                    raise HTTPException("connection closed before the end of the response")
                validators = Download(
                    None,
                    response.headers.get("ETag"),
                    response.headers.get("Last-Modified"),
                    response.headers.get("Content-Type"),
                )
        elif not scheme:
            with Path(source).open("rb") as file:
                data = file.read(max_bytes + 1)
        else:
            raise FeedError(f"unsupported feed source: {source} (use http(s) or a file path)")
    except HTTPError as error:
        error.close()
        if error.code == HTTPStatus.NOT_MODIFIED and (etag or last_modified):
            return Download(None, etag, last_modified)
        raise FeedError(f"cannot read {source}: {error}") from error
    except (OSError, HTTPException, ValueError) as error:
        detail = getattr(error, "reason", error)
        if isinstance(detail, socket.gaierror):
            # The libc message alone can be cryptic ("Try again" on musl).
            detail = f"cannot resolve host {urlsplit(source).hostname} ({detail.strerror})"
        raise FeedError(f"cannot read {source}: {detail}") from error
    if len(data) > max_bytes:
        raise FeedError(f"{source} is larger than {max_bytes} bytes")
    return replace(validators, data=data)


def _format_date(parsed: time.struct_time | None) -> str | None:
    if parsed is None:
        return None
    return f"{parsed.tm_year:04d}/{parsed.tm_mon:02d}/{parsed.tm_mday:02d}"


def fetch(source: str, now: datetime, cached: Feed | None = None) -> Feed | None:
    """Read and parse the feed at `source`.

    Returns None if the server says that `cached` is still up to date.
    """
    download = read_source(
        source,
        etag=cached.etag if cached else None,
        last_modified=cached.last_modified if cached else None,
    )
    if download.data is None:
        return None
    headers = {}
    if urlsplit(source).scheme in HTTP_SCHEMES:
        headers["content-location"] = source
    if download.content_type:
        headers["content-type"] = download.content_type
    parsed = feedparser.parse(download.data, response_headers=headers)
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
        etag=download.etag,
        last_modified=download.last_modified,
    )
