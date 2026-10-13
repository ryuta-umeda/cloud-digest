import re
from datetime import date, datetime, time, timedelta, timezone
from xml.etree import ElementTree

from digest.models import DigestEntry, DigestItem

ATOM_NS = "http://www.w3.org/2005/Atom"
FEED_TITLE = "クラウドダイジェスト"
DISCLAIMER = "※ AIによる自動要約です。正確な情報は元記事を確認してください。"
SEPARATOR = "──────────"
JST = timezone(timedelta(hours=9))
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
# XML 1.0 forbids most control characters; one stray char from a source feed would break the whole feed.
_INVALID_XML_CHARS = re.compile("[^\x09\x0a\x0d\x20-퟿-�\U00010000-\U0010ffff]")


def render_entry(items: list[DigestItem], day: date) -> DigestEntry:
    """Overview list first, details after: Viva Engage folds long posts, so the top must stand alone."""
    heading = f"【クラウドダイジェスト {day.month}/{day.day}】"
    overview = "\n".join(_render_overview_line(number, item) for number, item in enumerate(items, start=1))
    details = "\n\n".join(_render_detail(number, item) for number, item in enumerate(items, start=1))
    return DigestEntry(
        id=f"digest-{day.isoformat()}",
        title=heading,
        published=datetime.combine(day, time(0, 0), tzinfo=JST),
        body=f"{heading}\n今日の {len(items)} 件\n{overview}\n\n{SEPARATOR}\n\n{details}\n\n{DISCLAIMER}",
    )


def _render_overview_line(number: int, item: DigestItem) -> str:
    return f"{number}. {item.headline or item.title}（{item.source}）"


def _render_detail(number: int, item: DigestItem) -> str:
    lines = [f"{number}. {item.title}"]
    if item.summary:
        lines.append(item.summary)
    lines.append(f"→ {item.url}")
    return "\n".join(lines)


def build_atom(entries: list[DigestEntry], feed_url: str) -> str:
    ElementTree.register_namespace("", ATOM_NS)
    newest_first = sorted(entries, key=lambda entry: entry.published, reverse=True)
    feed = ElementTree.Element(f"{{{ATOM_NS}}}feed")
    _text_child(feed, "title", FEED_TITLE)
    _text_child(feed, "id", feed_url)
    _text_child(feed, "updated", (newest_first[0].published if newest_first else _EPOCH).isoformat())
    for entry in newest_first:
        element = ElementTree.SubElement(feed, f"{{{ATOM_NS}}}entry")
        _text_child(element, "id", entry.id)
        _text_child(element, "title", entry.title)
        _text_child(element, "updated", entry.published.isoformat())
        _text_child(element, "content", entry.body).set("type", "text")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ElementTree.tostring(feed, encoding="unicode")


def _text_child(parent: ElementTree.Element, tag: str, text: str) -> ElementTree.Element:
    child = ElementTree.SubElement(parent, f"{{{ATOM_NS}}}{tag}")
    child.text = _INVALID_XML_CHARS.sub("", text)
    return child


def validate_atom(xml: str) -> None:
    try:
        root = ElementTree.fromstring(xml.encode("utf-8"))
    except ElementTree.ParseError as error:
        raise ValueError(f"digest.xml is not well-formed: {error}") from error
    if root.tag != f"{{{ATOM_NS}}}feed":
        raise ValueError("digest.xml root must be an Atom feed")
    seen_ids: set[str] = set()
    for entry in root.findall(f"{{{ATOM_NS}}}entry"):
        fields = {tag: (entry.findtext(f"{{{ATOM_NS}}}{tag}") or "").strip() for tag in ("id", "title", "updated", "content")}
        missing = [tag for tag, value in fields.items() if not value]
        if missing:
            raise ValueError(f"entry is missing {missing}")
        if fields["id"] in seen_ids:
            raise ValueError(f"duplicate entry id: {fields['id']}")
        seen_ids.add(fields["id"])
