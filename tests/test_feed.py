import socket
from dataclasses import replace
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

import pytest
from conftest import FIXTURES, SAMPLE_FEED, FeedServer

from rss_reader_try.feed import Article, FeedError, NotModified, fetch, read_source

NOW = datetime(2026, 10, 13, 7, 15, tzinfo=UTC)


def test_fetch_rss_file() -> None:
    feed = fetch(str(SAMPLE_FEED), NOW)

    assert feed.source == str(SAMPLE_FEED)
    assert feed.title == "Sample Feed"
    assert feed.site_url == "https://example.com/"
    assert feed.fetched_at == NOW
    assert feed.articles[0] == Article(
        title="【サンプル】はじめての RSS リーダ",
        url="https://example.com/articles/3",
        date="2016/04/03",
    )
    assert [a.date for a in feed.articles] == ["2016/04/03", "2016/04/02", "2016/04/01"]


def test_fetch_atom_file() -> None:
    feed = fetch(str(FIXTURES / "atom.xml"), NOW)

    assert feed.title == "Atom Feed"
    assert feed.site_url == "https://atom.example.com/"
    assert feed.articles == (
        Article(title="Atom entry", url="https://atom.example.com/entry", date="2016/04/04"),
    )


def test_fetch_feed_without_articles() -> None:
    feed = fetch(str(FIXTURES / "empty.xml"), NOW)

    assert feed.title == "Empty Feed"
    assert feed.articles == ()


def test_missing_fields_get_fallbacks() -> None:
    source = str(FIXTURES / "sparse.xml")
    feed = fetch(source, NOW)

    assert feed.title == source
    assert feed.site_url == ""
    assert feed.articles == (Article(title="(no title)", url="", date=None),)


def test_not_a_feed() -> None:
    with pytest.raises(FeedError, match="not a feed"):
        fetch(str(FIXTURES / "not-a-feed.html"), NOW)


def test_missing_file() -> None:
    with pytest.raises(FeedError, match="No such file"):
        fetch(str(FIXTURES / "nope.xml"), NOW)


@pytest.mark.parametrize("source", ["file:///etc/passwd", "ftp://example.com/feed.xml"])
def test_unsupported_scheme(source: str) -> None:
    with pytest.raises(FeedError, match="unsupported"):
        fetch(source, NOW)


def test_external_entities_are_not_resolved(tmp_path: Path) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_text("TOP-SECRET")
    xxe = tmp_path / "xxe.xml"
    xxe.write_text(
        f'<?xml version="1.0"?>\n<!DOCTYPE rss [<!ENTITY xxe SYSTEM "{secret.as_uri()}">]>\n'
        '<rss version="2.0"><channel><title>t</title>'
        "<item><title>&xxe;</title></item></channel></rss>\n"
    )

    feed = fetch(str(xxe), NOW)

    assert "TOP-SECRET" not in repr(feed)


def test_file_size_limit(tmp_path: Path) -> None:
    big = tmp_path / "big.xml"
    big.write_bytes(b"x" * 11)

    with pytest.raises(FeedError, match="larger than 10 bytes"):
        read_source(str(big), max_bytes=10)
    assert read_source(str(big), max_bytes=11).data == b"x" * 11


def test_fetch_over_http(feed_server: FeedServer) -> None:
    feed_server.routes["/feed"] = (200, {}, SAMPLE_FEED.read_bytes())

    feed = fetch(feed_server.url("/feed"), NOW)

    assert feed.title == "Sample Feed"
    assert len(feed.articles) == 3
    assert feed_server.requests[0]["User-Agent"].startswith(
        f"rss-reader-try/{version('rss-reader-try')} "
    )
    assert "If-None-Match" not in feed_server.requests[0]


def test_relative_links_resolve_against_feed_url(feed_server: FeedServer) -> None:
    body = (
        b'<rss version="2.0"><channel><title>t</title><link>/</link>'
        b"<item><title>a</title><link>/posts/1</link></item></channel></rss>"
    )
    feed_server.routes["/blog/feed"] = (200, {}, body)

    feed = fetch(feed_server.url("/blog/feed"), NOW)

    assert feed.site_url == feed_server.url("/")
    assert feed.articles[0].url == feed_server.url("/posts/1")


def test_http_error(feed_server: FeedServer) -> None:
    with pytest.raises(FeedError, match="HTTP Error 404"):
        fetch(feed_server.url("/missing"), NOW)


def test_http_size_limit(feed_server: FeedServer) -> None:
    feed_server.routes["/big"] = (200, {}, b"x" * 11)

    with pytest.raises(FeedError, match="larger than 10 bytes"):
        read_source(feed_server.url("/big"), max_bytes=10)


def test_http_timeout(feed_server: FeedServer) -> None:
    feed_server.delay = 1.0
    feed_server.routes["/slow"] = (200, {}, SAMPLE_FEED.read_bytes())

    with pytest.raises(FeedError, match="timed out"):
        read_source(feed_server.url("/slow"), timeout=0.2)


def test_redirect_within_http_is_followed(feed_server: FeedServer) -> None:
    feed_server.routes["/old"] = (301, {"Location": feed_server.url("/new")}, b"")
    feed_server.routes["/new"] = (200, {}, SAMPLE_FEED.read_bytes())

    assert fetch(feed_server.url("/old"), NOW).title == "Sample Feed"


@pytest.mark.parametrize("target", ["ftp://127.0.0.1:1/feed.xml", "file:///etc/passwd"])
def test_redirect_to_other_scheme_is_refused(feed_server: FeedServer, target: str) -> None:
    feed_server.routes["/redirect"] = (302, {"Location": target}, b"")

    with pytest.raises(FeedError, match="redirect"):
        read_source(feed_server.url("/redirect"))


def test_truncated_response(feed_server: FeedServer) -> None:
    feed_server.routes["/truncated"] = (200, {"Content-Length": "1000"}, b"<rss")

    with pytest.raises(FeedError, match="cannot read"):
        read_source(feed_server.url("/truncated"))


@pytest.mark.parametrize("source", ["http://127.0.0.1:notaport/feed.xml", "http://[::1/feed.xml"])
def test_invalid_url(source: str) -> None:
    with pytest.raises(FeedError, match="cannot read"):
        fetch(source, NOW)


def test_unknown_host(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*_args: object, **_kwargs: object) -> None:
        raise socket.gaierror(socket.EAI_AGAIN, "Try again")

    monkeypatch.setattr(socket, "getaddrinfo", fail)

    with pytest.raises(FeedError, match=r"cannot resolve host feeds\.example \(Try again\)$"):
        read_source("http://feeds.example/feed.xml")


def test_fetch_keeps_validators(feed_server: FeedServer) -> None:
    validators = {"ETag": '"v1"', "Last-Modified": "Sun, 03 Apr 2016 12:00:00 GMT"}
    feed_server.routes["/feed"] = (200, validators, SAMPLE_FEED.read_bytes())

    feed = fetch(feed_server.url("/feed"), NOW)

    assert feed.etag == '"v1"'
    assert feed.last_modified == "Sun, 03 Apr 2016 12:00:00 GMT"


def test_not_modified(feed_server: FeedServer) -> None:
    validators = {"ETag": '"v1"', "Last-Modified": "Sun, 03 Apr 2016 12:00:00 GMT"}
    feed_server.routes["/feed"] = (200, validators, SAMPLE_FEED.read_bytes())
    cached = fetch(feed_server.url("/feed"), NOW)
    feed_server.routes["/feed"] = (304, {}, b"")

    with pytest.raises(NotModified):
        fetch(feed_server.url("/feed"), NOW, cached)

    assert feed_server.requests[1]["If-None-Match"] == '"v1"'
    assert feed_server.requests[1]["If-Modified-Since"] == "Sun, 03 Apr 2016 12:00:00 GMT"


def test_unexpected_not_modified_is_an_error(feed_server: FeedServer) -> None:
    feed_server.routes["/feed"] = (304, {}, b"")

    with pytest.raises(FeedError, match="HTTP Error 304"):
        fetch(feed_server.url("/feed"), NOW)


def test_local_file_ignores_validators() -> None:
    cached = fetch(str(SAMPLE_FEED), NOW)

    assert fetch(str(SAMPLE_FEED), NOW, replace(cached, etag='"v1"')).title == "Sample Feed"


def test_charset_from_http_header(feed_server: FeedServer) -> None:
    body = (
        '<rss version="2.0"><channel><title>東方スレ観測所</title>'
        "<item><title>こいしにマシンガン</title></item></channel></rss>"
    ).encode("shift_jis")
    content_type = {"Content-Type": "application/rss+xml; charset=Shift_JIS"}
    feed_server.routes["/sjis"] = (200, content_type, body)

    feed = fetch(feed_server.url("/sjis"), NOW)

    assert feed.title == "東方スレ観測所"
    assert feed.articles[0].title == "こいしにマシンガン"


def test_charset_from_xml_declaration(tmp_path: Path) -> None:
    path = tmp_path / "eucjp.xml"
    path.write_bytes(
        '<?xml version="1.0" encoding="EUC-JP"?>\n<rss version="2.0"><channel>'
        "<title>日本語のフィード</title></channel></rss>".encode("euc_jp")
    )

    feed = fetch(str(path), NOW)

    assert feed.title == "日本語のフィード"


@pytest.mark.parametrize("content_type", ["text/plain", "text/html; charset=utf-8"])
def test_feed_with_wrong_content_type_still_parses(
    feed_server: FeedServer, content_type: str
) -> None:
    feed_server.routes["/feed"] = (200, {"Content-Type": content_type}, SAMPLE_FEED.read_bytes())

    feed = fetch(feed_server.url("/feed"), NOW)

    assert feed.title == "Sample Feed"
    assert len(feed.articles) == 3


def page_linking_to(href: str, feed_type: str = "application/rss+xml") -> bytes:
    return (
        "<!doctype html><html><head><title>Blog</title>"
        f'<link rel="stylesheet" href="/style.css">'
        f'<link rel="alternate" type="{feed_type}" title="RSS" href="{href}">'
        "</head><body>hello</body></html>"
    ).encode()


@pytest.mark.parametrize("feed_type", ["application/rss+xml", "application/atom+xml"])
def test_discover_feed_from_page(feed_server: FeedServer, feed_type: str) -> None:
    feed_server.routes["/blog/"] = (
        200,
        {"Content-Type": "text/html"},
        page_linking_to("feed.xml", feed_type),
    )
    feed_server.routes["/blog/feed.xml"] = (200, {"ETag": '"v1"'}, SAMPLE_FEED.read_bytes())

    feed = fetch(feed_server.url("/blog/"), NOW)

    assert feed.source == feed_server.url("/blog/")
    assert feed.title == "Sample Feed"
    assert len(feed.articles) == 3
    # Validators belong to the feed, but refreshes ask the page, so they are not kept.
    assert feed.etag is None
    assert feed.last_modified is None


@pytest.mark.parametrize(
    "body",
    [
        b"<!doctype html><html><head><title>No feed</title></head><body></body></html>",
        page_linking_to("javascript:alert(1)"),
        page_linking_to("file:///etc/passwd"),
    ],
)
def test_page_without_usable_feed_link(feed_server: FeedServer, body: bytes) -> None:
    feed_server.routes["/"] = (200, {"Content-Type": "text/html"}, body)

    with pytest.raises(FeedError, match="not a feed"):
        fetch(feed_server.url("/"), NOW)
    assert len(feed_server.requests) == 1


def test_discovery_follows_one_link_only(feed_server: FeedServer) -> None:
    feed_server.routes["/a"] = (200, {}, page_linking_to("/b"))
    feed_server.routes["/b"] = (200, {}, page_linking_to("/c"))

    with pytest.raises(FeedError, match=r"not a feed: http://.*/b \(found in http://.*/a\)"):
        fetch(feed_server.url("/a"), NOW)
    assert len(feed_server.requests) == 2


def test_no_discovery_for_local_files(tmp_path: Path) -> None:
    feed = tmp_path / "feed.xml"
    feed.write_bytes(SAMPLE_FEED.read_bytes())
    page = tmp_path / "page.html"
    page.write_bytes(page_linking_to("feed.xml"))

    with pytest.raises(FeedError, match="not a feed"):
        fetch(str(page), NOW)
