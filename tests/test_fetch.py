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
    assert articles[0].id == "https://e/a"
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
