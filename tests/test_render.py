from datetime import UTC, datetime
from pathlib import Path

import pytest
from conftest import FIXTURES

from rss_reader_try.feed import Article, Feed, fetch
from rss_reader_try.render import format_time, output_filename, render_html, write_html

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


def test_write_html_creates_directory(tmp_path: Path) -> None:
    out = tmp_path / "nested" / "html"

    path = write_html(FEED, out)

    assert path == out / "Example.html"
    assert path.read_text(encoding="utf-8") == render_html(FEED)


def test_write_html_stays_inside_out_dir(tmp_path: Path) -> None:
    feed = fetch(str(FIXTURES / "malicious.xml"), NOW)

    path = write_html(feed, tmp_path)

    assert path.parent == tmp_path
