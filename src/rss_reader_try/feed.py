"""Read a feed from a URL or a local file and turn it into plain data."""

import socket
import time
from dataclasses import dataclass, replace
from datetime import datetime
from html.parser import HTMLParser
from http import HTTPStatus
from http.client import HTTPException, HTTPMessage
from importlib.metadata import version
from pathlib import Path
from typing import IO, override
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

import feedparser

USER_AGENT = (
    f"rss-reader-try/{version('rss-reader-try')} (+https://github.com/yuu-eguci/rss-reader-try)"
)
TIMEOUT_SECONDS = 30.0
MAX_BYTES = 10 * 1024 * 1024
HTTP_SCHEMES = frozenset({"http", "https"})
FEED_TYPES = frozenset({"application/rss+xml", "application/atom+xml"})


class FeedError(Exception):
    """The feed could not be read."""


class NotModified(Exception):  # noqa: N818 - named after HTTP 304
    """The server says the cached copy is still up to date."""


@dataclass(frozen=True)
class Article:
    title: str
    url: str
    date: str | None  # "YYYY/MM/DD"
    new: bool = False  # not in the previously fetched copy


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
    data: bytes
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
        headers: HTTPMessage,
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
    """Read an http(s) URL or a local file.

    Raises NotModified if validators are given and the server answers 304.
    """
    response_headers: HTTPMessage | None = None
    try:
        scheme = urlsplit(source).scheme
        if scheme in HTTP_SCHEMES:
            request_headers = {"User-Agent": USER_AGENT}
            if etag:
                request_headers["If-None-Match"] = etag
            if last_modified:
                request_headers["If-Modified-Since"] = last_modified
            opener = build_opener(_HttpOnlyRedirectHandler)
            request = Request(source, headers=request_headers)  # noqa: S310 - scheme checked
            with opener.open(request, timeout=timeout) as response:
                data = response.read(max_bytes + 1)
                if len(data) <= max_bytes and response.length:
                    raise HTTPException("connection closed before the end of the response")
                response_headers = response.headers
        elif not scheme:
            with Path(source).open("rb") as file:
                data = file.read(max_bytes + 1)
        else:
            raise FeedError(f"unsupported feed source: {source} (use http(s) or a file path)")
    except HTTPError as error:
        error.close()
        if error.code == HTTPStatus.NOT_MODIFIED and (etag or last_modified):
            raise NotModified from error
        raise FeedError(f"cannot read {source}: {error}") from error
    except (OSError, HTTPException, ValueError) as error:
        detail = getattr(error, "reason", error)
        if isinstance(detail, socket.gaierror):
            # The libc message alone can be cryptic ("Try again" on musl).
            detail = f"cannot resolve host {urlsplit(source).hostname} ({detail.strerror})"
        raise FeedError(f"cannot read {source}: {detail}") from error
    if len(data) > max_bytes:
        raise FeedError(f"{source} is larger than {max_bytes} bytes")
    if response_headers is None:
        return Download(data)
    return Download(
        data,
        response_headers.get("ETag"),
        response_headers.get("Last-Modified"),
        response_headers.get("Content-Type"),
    )


def _format_date(parsed: time.struct_time | None) -> str | None:
    if parsed is None:
        return None
    return f"{parsed.tm_year:04d}/{parsed.tm_mon:02d}/{parsed.tm_mday:02d}"


def mark_new(feed: Feed, previous: Feed) -> Feed:
    """Flag the articles of `feed` that `previous` did not have."""
    seen = {article.url or article.title for article in previous.articles}
    return replace(
        feed,
        articles=tuple(
            replace(article, new=(article.url or article.title) not in seen)
            for article in feed.articles
        ),
    )


class _FeedLinkFinder(HTMLParser):
    """Collect hrefs of <link rel="alternate" type="application/rss+xml" ...> tags."""

    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    @override
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {name: value or "" for name, value in attrs}
        if (
            tag == "link"
            and "alternate" in values.get("rel", "").lower().split()
            and values.get("type", "").lower() in FEED_TYPES
            and values.get("href")
        ):
            self.hrefs.append(values["href"])


def _discover(page_url: str, data: bytes) -> str | None:
    """Return the first http(s) feed URL that the HTML page links to."""
    finder = _FeedLinkFinder()
    finder.feed(data.decode("utf-8", errors="replace"))
    for href in finder.hrefs:
        url = urljoin(page_url, href.strip())
        if urlsplit(url).scheme in HTTP_SCHEMES:
            return url
    return None


def _parse(url: str, download: Download) -> feedparser.FeedParserDict | None:
    headers = {}
    if urlsplit(url).scheme in HTTP_SCHEMES:
        headers["content-location"] = url
    if download.content_type:
        headers["content-type"] = download.content_type
    parsed = feedparser.parse(download.data, response_headers=headers)
    return parsed if parsed.get("version") or parsed.entries else None


def fetch(source: str, now: datetime, cached: Feed | None = None) -> Feed:
    """Read and parse the feed at `source`, or the feed that the page at `source` links to.

    With `cached`, ask the server only for changes (raises NotModified if there are none).
    """
    download = read_source(
        source,
        etag=cached.etag if cached else None,
        last_modified=cached.last_modified if cached else None,
    )
    parsed = _parse(source, download)
    if parsed is None:
        is_http = urlsplit(source).scheme in HTTP_SCHEMES
        feed_url = _discover(source, download.data) if is_http else None
        if feed_url is None:
            raise FeedError(f"not a feed: {source}")
        # Refreshes ask the page again, so the feed's validators would be wrong there.
        download = replace(read_source(feed_url), etag=None, last_modified=None)
        parsed = _parse(feed_url, download)
        if parsed is None:
            raise FeedError(f"not a feed: {feed_url} (found in {source})")
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
