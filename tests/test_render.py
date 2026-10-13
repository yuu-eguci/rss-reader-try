from dataclasses import replace
from datetime import UTC, datetime

import pytest
from conftest import FIXTURES

from rss_reader_try.feed import Article, Feed, fetch
from rss_reader_try.render import format_time, output_filename, render_html, render_index

NOW = datetime(2026, 10, 13, 7, 15, tzinfo=UTC)
FEED = Feed(
    source="https://example.com/feed.xml",
    title="Example",
    site_url="https://example.com/",
    fetched_at=NOW,
    articles=(
        Article(title="first", url="https://example.com/1", date="2016/04/03"),
        Article(title="no date", url="", date=None),
    ),
)


def test_format_time() -> None:
    assert format_time(NOW) == "2026/10/13 07:15 UTC"


def test_render_lists_articles() -> None:
    html = render_html(FEED)

    assert '<meta charset="utf-8">' in html
    assert "<title>自作PythonRSS</title>" in html
    assert 'Articles of site: <a href="https://example.com/"' in html
    link = '<a href="https://example.com/1" rel="noopener noreferrer">first</a>'
    assert f"2016/04/03 -- {link}</li>" in html
    assert "----/--/-- -- no date</li>" in html
    assert "This RSS was made at 2026/10/13 07:15 UTC" in html


def test_render_has_csp_without_scripts() -> None:
    html = render_html(FEED)

    assert "Content-Security-Policy" in html
    assert "default-src 'none'" in html
    assert "<script" not in html


def test_render_escapes_feed_content() -> None:
    feed = fetch(str(FIXTURES / "malicious.xml"), NOW)

    html = render_html(feed)

    assert "<script>" not in html
    assert "<img" not in html
    assert "javascript:" not in html
    assert "&lt;img src=x onerror=alert(1)&gt;" in html
    assert 'href="https://example.com/?a=1&amp;b=&#x27;2&#x27;"' in html
    assert "quote &#x27; and &quot; and &amp;" in html


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Sample Feed", "Sample-Feed.html"),
        ("mpywの記事 - Qiita", "mpywの記事-Qiita.html"),
        ("../../etc/passwd", "etc-passwd.html"),
        ("a/b\\c:d*e?f", "a-b-c-d-e-f.html"),
        ("!!!", "feed.html"),
        ("", "feed.html"),
        ("x" * 200, "x" * 100 + ".html"),
    ],
)
def test_output_filename(title: str, expected: str) -> None:
    assert output_filename(title) == expected


@pytest.mark.parametrize(
    ("title", "taken", "expected"),
    [
        ("Sample Feed", {"Other.html"}, "Sample-Feed.html"),
        ("Sample Feed", {"sample-feed.html"}, "Sample-Feed-2.html"),
        ("Sample Feed", {"Sample-Feed.html", "Sample-Feed-2.html"}, "Sample-Feed-3.html"),
        ("index", {"index.html"}, "index-2.html"),
    ],
)
def test_output_filename_avoids_taken_names(title: str, taken: set[str], expected: str) -> None:
    assert output_filename(title, taken) == expected


def test_render_index() -> None:
    other = Feed(
        source="other.xml",
        title="mpywの記事 <Qiita>",
        site_url="",
        fetched_at=datetime(2026, 10, 12, 1, 2, tzinfo=UTC),
        articles=(FEED.articles[0],),
    )

    html = render_index([(FEED, "Example.html"), (other, "mpywの記事-Qiita.html")], NOW)

    assert "default-src 'none'" in html
    assert (
        '<li><a href="Example.html">Example</a> -- 2 articles (fetched 2026/10/13 07:15 UTC)</li>'
    ) in html
    assert (
        '<li><a href="mpyw%E3%81%AE%E8%A8%98%E4%BA%8B-Qiita.html">mpywの記事 &lt;Qiita&gt;</a>'
        " -- 1 article (fetched 2026/10/12 01:02 UTC)</li>"
    ) in html
    assert "This index was made at 2026/10/13 07:15 UTC" in html


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "JavaScript:alert(1)",
        " javascript:alert(1)",
        "\x01javascript:alert(1)",
        "java\tscript:alert(1)",
        "java\nscript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "vbscript:msgbox(1)",
        "//evil.example/",
        "/relative/path",
    ],
)
def test_only_http_links_are_linked(url: str) -> None:
    feed = Feed(
        source="x",
        title="t",
        site_url=url,
        fetched_at=NOW,
        articles=(Article(title="a", url=url, date=None),),
    )

    html = render_html(feed)

    assert "<a " not in html


def test_new_articles_are_marked() -> None:
    feed = replace(
        FEED,
        articles=(
            Article(title="fresh", url="https://example.com/2", date="2016/04/04", new=True),
            *FEED.articles,
        ),
    )

    html = render_html(feed)
    index = render_index([(feed, "Example.html")], NOW)

    assert '<li>2016/04/04 -- <strong>NEW</strong> <a href="https://example.com/2"' in html
    assert html.count("NEW") == 1
    assert " -- 3 articles, 1 new (fetched " in index
