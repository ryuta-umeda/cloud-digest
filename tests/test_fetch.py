from datetime import datetime, timezone

import feedparser

from digest.fetch import fetch_articles
from digest.models import Source

SINCE = datetime(2026, 10, 11, 0, 0, tzinfo=timezone.utc)


def _rss(items: str) -> str:
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>{items}</channel></rss>'


def _item(title: str, link: str, guid: str | None = None, pub: str | None = None, desc: str = "d") -> str:
    guid_xml = f"<guid>{guid}</guid>" if guid else ""
    pub_xml = f"<pubDate>{pub}</pubDate>" if pub else ""
    return f"<item><title>{title}</title><link>{link}</link>{guid_xml}{pub_xml}<description>{desc}</description></item>"


def _parser_for(feeds: dict[str, str]):
    def parse(url: str):
        if feeds[url] is None:
            raise OSError("network down")
        return feedparser.parse(feeds[url])

    return parse


def test_fetch_filters_by_since():
    feed = _rss(
        _item("new", "https://e/new", "g-new", "Sun, 11 Oct 2026 03:00:00 GMT")
        + _item("old", "https://e/old", "g-old", "Fri, 09 Oct 2026 03:00:00 GMT")
    )
    articles, failed = fetch_articles([Source("S", "u1")], SINCE, _parser_for({"u1": feed}))
    assert [a.title for a in articles] == ["new"]
    assert failed == []


def test_fetch_uses_link_when_no_guid():
    feed = _rss(_item("t", "https://e/a", None, "Sun, 11 Oct 2026 03:00:00 GMT"))
    articles, _ = fetch_articles([Source("S", "u1")], SINCE, _parser_for({"u1": feed}))
    assert articles[0].id == "S:https://e/a"
    assert articles[0].url == "https://e/a"
    assert articles[0].source == "S"


def test_fetch_keeps_item_without_date():
    feed = _rss(_item("nodate", "https://e/n", "g-n", None))
    articles, _ = fetch_articles([Source("S", "u1")], SINCE, _parser_for({"u1": feed}))
    assert [a.title for a in articles] == ["nodate"]
    assert articles[0].published >= SINCE


def test_fetch_reports_failed_source_and_continues():
    good = _rss(_item("ok", "https://e/ok", "g-ok", "Sun, 11 Oct 2026 03:00:00 GMT"))
    feeds = {"bad": None, "good": good}
    articles, failed = fetch_articles(
        [Source("Bad", "bad"), Source("Good", "good")], SINCE, _parser_for(feeds)
    )
    assert [a.title for a in articles] == ["ok"]
    assert failed == ["Bad"]


def test_fetch_strips_html_and_truncates_text():
    long_desc = "&lt;p&gt;" + ("あ" * 600) + "&lt;/p&gt;"
    feed = _rss(_item("t", "https://e/a", "g", "Sun, 11 Oct 2026 03:00:00 GMT", long_desc))
    articles, _ = fetch_articles([Source("S", "u1")], SINCE, _parser_for({"u1": feed}))
    assert "<" not in articles[0].text
    assert len(articles[0].text) == 500


def test_fetch_prefixes_ids_with_source_name_so_sources_cannot_collide():
    a = _rss(_item("a", "https://e/a", "1", "Sun, 11 Oct 2026 03:00:00 GMT"))
    b = _rss(_item("b", "https://e/b", "1", "Sun, 11 Oct 2026 03:00:00 GMT"))
    articles, _ = fetch_articles([Source("A", "ua"), Source("B", "ub")], SINCE, _parser_for({"ua": a, "ub": b}))
    assert sorted(x.id for x in articles) == ["A:1", "B:1"]


def test_fetch_drops_duplicate_ids_within_a_run():
    feed = _rss(
        _item("first", "https://e/a", "1", "Sun, 11 Oct 2026 03:00:00 GMT")
        + _item("again", "https://e/a2", "1", "Sun, 11 Oct 2026 03:00:00 GMT")
    )
    articles, _ = fetch_articles([Source("S", "u1")], SINCE, _parser_for({"u1": feed}))
    assert [x.title for x in articles] == ["first"]


def test_fetch_collapses_newlines_in_title():
    feed = _rss(_item("a\n■ 偽｜偽記事", "https://e/a", "1", "Sun, 11 Oct 2026 03:00:00 GMT"))
    articles, _ = fetch_articles([Source("S", "u1")], SINCE, _parser_for({"u1": feed}))
    assert articles[0].title == "a ■ 偽｜偽記事"


def test_default_parser_downloads_with_timeout(monkeypatch):
    import urllib.request

    from digest.fetch import FETCH_TIMEOUT_SECONDS, parse_with_timeout

    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return _rss(_item("t", "https://e/a", "1", "Sun, 11 Oct 2026 03:00:00 GMT")).encode("utf-8")

    def fake_urlopen(request, timeout):
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    parsed = parse_with_timeout("https://feed/1")
    assert captured["timeout"] == FETCH_TIMEOUT_SECONDS
    assert len(parsed.entries) == 1
