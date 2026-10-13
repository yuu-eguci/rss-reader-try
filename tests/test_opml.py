from pathlib import Path
from xml.etree import ElementTree

import pytest

from rss_reader_try.opml import read_opml


def test_nested_outlines_in_document_order(tmp_path: Path) -> None:
    opml = tmp_path / "subs.opml"
    opml.write_text(
        '<opml version="1.0"><body><outline text="a" xmlUrl=" https://a.example/feed "/>'
        '<outline text="folder"><outline text="b" xmlUrl="https://b.example/feed"/></outline>'
        '<outline text="empty" xmlUrl=""/></body></opml>'
    )

    assert read_opml(opml) == ["https://a.example/feed", "https://b.example/feed"]


def test_not_an_opml_file() -> None:
    sample = Path(__file__).parent.parent / "examples" / "sample-feed.xml"

    with pytest.raises(ValueError, match="not an OPML file"):
        read_opml(sample)


def test_external_entities_are_not_loaded(tmp_path: Path) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_text("TOP-SECRET")
    opml = tmp_path / "xxe.opml"
    opml.write_text(
        f'<?xml version="1.0"?><!DOCTYPE opml [<!ENTITY xxe SYSTEM "{secret.as_uri()}">]>'
        '<opml><body><outline xmlUrl="&xxe;"/></body></opml>'
    )

    with pytest.raises(ElementTree.ParseError, match="external entity"):
        read_opml(opml)


def test_entity_expansion_bomb_is_refused(tmp_path: Path) -> None:
    entities = '<!ENTITY a0 "lol">' + "".join(
        f'<!ENTITY a{i} "{f"&a{i - 1};" * 10}">' for i in range(1, 10)
    )
    opml = tmp_path / "bomb.opml"
    opml.write_text(
        f'<?xml version="1.0"?><!DOCTYPE opml [{entities}]>'
        '<opml><body><outline xmlUrl="&a9;"/></body></opml>'
    )

    with pytest.raises(ElementTree.ParseError, match="amplification"):
        read_opml(opml)
