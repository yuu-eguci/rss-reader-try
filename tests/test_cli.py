import shutil
import webbrowser
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from conftest import FIXTURES, SAMPLE_FEED, FeedServer

from rss_reader_try.cli import is_fresh, run


def fake_browser(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    opened: list[str] = []

    def fake_open(url: str) -> bool:
        opened.append(url)
        return True

    monkeypatch.setattr(webbrowser, "open", fake_open)
    return opened


@pytest.fixture
def workdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    shutil.copy(SAMPLE_FEED, tmp_path / "feed.xml")
    shutil.copy(FIXTURES / "atom.xml", tmp_path / "atom.xml")
    return tmp_path


def test_first_run_fetches_and_writes_html(
    workdir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(["feed.xml"]) == 0

    out, err = capsys.readouterr()
    assert out == 'fetched: 3 articles from "Sample Feed" -> html/Sample-Feed.html\n'
    assert err == ""
    assert "はじめての RSS リーダ" in (workdir / "html" / "Sample-Feed.html").read_text()
    assert (workdir / "my_rss.sqlite3").exists()
    assert not (workdir / "html" / "index.html").exists()


def test_second_run_uses_cache(workdir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run(["feed.xml"])
    capsys.readouterr()
    (workdir / "feed.xml").write_text("changed, but the cache is still fresh")

    assert run(["feed.xml"]) == 0

    out = capsys.readouterr().out
    assert out.startswith('cache: 3 articles from "Sample Feed" (fetched ')
    assert out.endswith(" UTC) -> html/Sample-Feed.html\n")


def test_max_age_zero_always_fetches(workdir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run(["feed.xml"])
    (workdir / "feed.xml").write_text((FIXTURES / "empty.xml").read_text())
    capsys.readouterr()

    assert run(["--max-age", "0", "feed.xml"]) == 0

    assert capsys.readouterr().out == (
        'fetched: 0 articles from "Empty Feed" -> html/Empty-Feed.html\n'
    )


def test_custom_db_and_out(workdir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(["--db", "data/cache.db", "--out", "pages", "feed.xml"]) == 0

    assert capsys.readouterr().out.endswith("-> pages/Sample-Feed.html\n")
    assert (workdir / "data" / "cache.db").exists()
    assert (workdir / "pages" / "Sample-Feed.html").exists()


def test_feed_error_exits_with_1(workdir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(["missing.xml"]) == 1

    out, err = capsys.readouterr()
    assert out == ""
    assert err.startswith("error: cannot read missing.xml: ")
    assert "Traceback" not in err
    assert not (workdir / "html").exists()


def test_unwritable_out_exits_with_1(workdir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (workdir / "html").write_text("a file, not a directory")

    assert run(["feed.xml"]) == 1

    assert capsys.readouterr().err.startswith("error: ")


@pytest.mark.parametrize("value", ["-1", "abc", "nan", "inf", "1e20"])
def test_invalid_max_age(workdir: Path, value: str, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        run(["--max-age", value, "feed.xml"])

    assert excinfo.value.code == 2
    assert "--max-age" in capsys.readouterr().err


def test_open_in_browser(workdir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    opened = fake_browser(monkeypatch)

    assert run(["--open", "feed.xml"]) == 0

    assert opened == [(workdir / "html" / "Sample-Feed.html").resolve().as_uri()]


def test_open_without_browser_warns(
    workdir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(webbrowser, "open", lambda _url: False)

    assert run(["--open", "feed.xml"]) == 0

    assert "warning: could not open a browser" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("age", "fresh"),
    [
        (timedelta(0), True),
        (timedelta(hours=6) - timedelta(seconds=1), True),
        (timedelta(hours=6), False),
        (timedelta(days=1), False),
    ],
)
def test_is_fresh_boundary(age: timedelta, fresh: bool) -> None:
    now = datetime(2026, 10, 13, tzinfo=UTC)

    assert is_fresh(now - age, now, timedelta(hours=6)) is fresh


def test_corrupt_database_exits_with_1(workdir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (workdir / "my_rss.sqlite3").write_text("not a database")

    assert run(["feed.xml"]) == 1

    assert capsys.readouterr().err == "error: my_rss.sqlite3: file is not a database\n"


def test_single_article_is_singular(workdir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(["atom.xml"]) == 0

    assert capsys.readouterr().out == 'fetched: 1 article from "Atom Feed" -> html/Atom-Feed.html\n'


def test_failed_refresh_falls_back_to_stale_cache(
    workdir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run(["feed.xml"])
    (workdir / "feed.xml").unlink()
    capsys.readouterr()

    assert run(["--max-age", "0", "feed.xml"]) == 0

    out, err = capsys.readouterr()
    assert out.startswith('cache: 3 articles from "Sample Feed" (fetched ')
    assert err.startswith("warning: cannot read feed.xml: ")
    assert err.endswith("; using the cached copy\n")


def test_multiple_feeds_write_an_index(workdir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(["feed.xml", "atom.xml"]) == 0

    assert capsys.readouterr().out == (
        'fetched: 3 articles from "Sample Feed" -> html/Sample-Feed.html\n'
        'fetched: 1 article from "Atom Feed" -> html/Atom-Feed.html\n'
        "index: 2 pages -> html/index.html\n"
    )
    index = (workdir / "html" / "index.html").read_text()
    assert '<a href="Sample-Feed.html">Sample Feed</a>' in index
    assert '<a href="Atom-Feed.html">Atom Feed</a>' in index


def test_failing_feed_does_not_stop_the_others(
    workdir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(["feed.xml", "missing.xml", "atom.xml"]) == 1

    out, err = capsys.readouterr()
    assert out.splitlines()[-1] == "index: 2 pages -> html/index.html"
    assert err.startswith("error: cannot read missing.xml: ")


def test_all_feeds_failing_writes_no_index(
    workdir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(["missing.xml", "nope.xml"]) == 1

    out, err = capsys.readouterr()
    assert out == ""
    assert err.count("error: ") == 2
    assert not (workdir / "html" / "index.html").exists()


def test_same_title_gets_another_file(workdir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    shutil.copy(SAMPLE_FEED, workdir / "copy.xml")

    assert run(["feed.xml", "copy.xml"]) == 0

    out = capsys.readouterr().out
    assert "-> html/Sample-Feed.html\n" in out
    assert "-> html/Sample-Feed-2.html\n" in out


def test_open_multiple_feeds_opens_index(workdir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    opened = fake_browser(monkeypatch)

    assert run(["--open", "feed.xml", "atom.xml"]) == 0

    assert opened == [(workdir / "html" / "index.html").resolve().as_uri()]


def test_index_with_one_page_is_singular(workdir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(["feed.xml", "missing.xml"]) == 1

    assert capsys.readouterr().out.endswith("index: 1 page -> html/index.html\n")


def test_repeated_feed_is_read_once(workdir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(["feed.xml", "atom.xml", "feed.xml"]) == 0

    assert capsys.readouterr().out == (
        'fetched: 3 articles from "Sample Feed" -> html/Sample-Feed.html\n'
        'fetched: 1 article from "Atom Feed" -> html/Atom-Feed.html\n'
        "index: 2 pages -> html/index.html\n"
    )


def test_not_modified_reuses_cache(
    workdir: Path, feed_server: FeedServer, capsys: pytest.CaptureFixture[str]
) -> None:
    url = feed_server.url("/feed")
    feed_server.routes["/feed"] = (200, {"ETag": '"v1"'}, SAMPLE_FEED.read_bytes())
    run([url])
    feed_server.routes["/feed"] = (304, {}, b"")
    capsys.readouterr()

    assert run(["--max-age", "0", url]) == 0
    assert run([url]) == 0

    out = capsys.readouterr().out.splitlines()
    assert (
        out[0] == 'fetched: 3 articles from "Sample Feed" (not modified) -> html/Sample-Feed.html'
    )
    assert out[1].startswith('cache: 3 articles from "Sample Feed"')
    assert len(feed_server.requests) == 2
