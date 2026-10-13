"""Read feed URLs from an OPML subscription list."""

from pathlib import Path
from xml.etree import ElementTree


def read_opml(path: Path) -> list[str]:
    """Return the xmlUrl of every <outline> in the OPML file, in document order."""
    # A local file chosen by the user; expat refuses external entities and entity bombs.
    root = ElementTree.parse(path).getroot()  # noqa: S314
    if root.tag != "opml":
        raise ValueError("not an OPML file")
    return [url for outline in root.iter("outline") if (url := outline.get("xmlUrl", "").strip())]
