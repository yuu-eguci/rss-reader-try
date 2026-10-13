import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from conftest import FIXTURES, SAMPLE_FEED

from rss_reader_try import cli
from rss_reader_try.cli import is_fresh, run


@pytest.fixture
def workdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    shutil.copy(SAMPLE_FEED, tmp_path / "feed.xml")
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


@pytest.mark.parametrize("value", ["-1", "abc"])
def test_invalid_max_age(workdir: Path, value: str, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        run(["--max-age", value, "feed.xml"])

    assert excinfo.value.code == 2
    assert "--max-age" in capsys.readouterr().err


def test_open_in_browser(workdir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[str] = []
    monkeypatch.setattr(cli.webbrowser, "open", lambda url: opened.append(url) or True)

    assert run(["--open", "feed.xml"]) == 0

    assert opened == [(workdir / "html" / "Sample-Feed.html").resolve().as_uri()]


def test_open_without_browser_warns(
    workdir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli.webbrowser, "open", lambda _url: False)

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
    shutil.copy(FIXTURES / "atom.xml", workdir / "atom.xml")

    assert run(["atom.xml"]) == 0

    assert capsys.readouterr().out == 'fetched: 1 article from "Atom Feed" -> html/Atom-Feed.html\n'
