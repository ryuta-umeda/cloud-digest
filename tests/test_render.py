from datetime import date, datetime, timedelta, timezone
from xml.etree import ElementTree

import pytest

from digest.models import DigestEntry, DigestItem
from digest.render import build_atom, render_entry, validate_atom

FEED_URL = "https://example.github.io/cloud-digest/digest.xml"
ATOM = "{http://www.w3.org/2005/Atom}"
JST = timezone(timedelta(hours=9))


def _entry(day: int, body: str = "本文") -> DigestEntry:
    return DigestEntry(f"digest-2026-10-{day:02d}", f"【クラウドダイジェスト 10/{day}】", datetime(2026, 10, day, tzinfo=JST), body)


def test_render_entry_lists_overview_before_details():
    items = [
        DigestItem("AWS", "Title A", "要約A", "https://e/a", "見出しA"),
        DigestItem("Azure", "Title B", "要約B", "https://e/b"),
    ]
    entry = render_entry(items, date(2026, 10, 7))
    assert entry.id == "digest-2026-10-07"
    assert entry.title == "【クラウドダイジェスト 10/7】"
    assert entry.body == (
        "【クラウドダイジェスト 10/7】\n"
        "今日の 2 件\n"
        "1. 見出しA（AWS）\n"
        "2. Title B（Azure）\n"
        "\n"
        "──────────\n"
        "\n"
        "1. Title A\n要約A\n→ https://e/a\n"
        "\n"
        "2. Title B\n要約B\n→ https://e/b\n"
        "\n"
        "※ AIによる自動要約です。正確な情報は元記事を確認してください。"
    )


def test_render_entry_omits_summary_line_for_fallback():
    entry = render_entry([DigestItem("AWS", "Title A", "", "https://e/a")], date(2026, 10, 7))
    assert "1. Title A\n→ https://e/a" in entry.body
    assert entry.body.count("Title A") == 2


def test_build_atom_strips_invalid_xml_chars():
    xml = build_atom([_entry(12, "bad\x00char\x0bhere")], FEED_URL)
    validate_atom(xml)
    content = ElementTree.fromstring(xml).find(f"{ATOM}entry/{ATOM}content").text
    assert content == "badcharhere"


def test_build_atom_is_valid_with_emoji_and_japanese():
    xml = build_atom([_entry(12, "新機能 🚀 のお知らせ & <script>")], FEED_URL)
    validate_atom(xml)
    content = ElementTree.fromstring(xml).find(f"{ATOM}entry/{ATOM}content").text
    assert content == "新機能 🚀 のお知らせ & <script>"


def test_build_atom_orders_newest_first():
    xml = build_atom([_entry(9), _entry(12), _entry(10)], FEED_URL)
    ids = [e.find(f"{ATOM}id").text for e in ElementTree.fromstring(xml).findall(f"{ATOM}entry")]
    assert ids == ["digest-2026-10-12", "digest-2026-10-10", "digest-2026-10-09"]


def test_build_atom_with_no_entries_is_valid():
    validate_atom(build_atom([], FEED_URL))


def test_validate_atom_rejects_duplicate_ids():
    xml = build_atom([_entry(12), _entry(12)], FEED_URL)
    with pytest.raises(ValueError, match="duplicate"):
        validate_atom(xml)


def test_validate_atom_rejects_malformed_xml():
    with pytest.raises(ValueError):
        validate_atom("<feed>")
