import re
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

import feedparser

from digest.models import Article, Source

TEXT_MAX_CHARS = 500
_TAG_PATTERN = re.compile(r"<[^>]+>")


def fetch_articles(
    sources: list[Source],
    since: datetime,
    parse: Callable[[str], Any] = feedparser.parse,
) -> tuple[list[Article], list[str]]:
    """Return (articles published at or after `since`, names of sources that failed).

    One failing source never aborts the others. Items without a publish date are
    kept (dated `since`) so a feed that omits dates is not silently dropped.
    """
    articles: list[Article] = []
    failed: list[str] = []
    for source in sources:
        try:
            parsed = parse(source.url)
        except Exception:
            failed.append(source.name)
            continue
        if parsed.get("bozo") and not parsed.get("entries"):
            failed.append(source.name)
            continue
        articles.extend(_to_articles(source, parsed.entries, since))
    return articles, failed


def _to_articles(source: Source, entries: list[Any], since: datetime) -> list[Article]:
    converted = (_to_article(source, entry, since) for entry in entries)
    return [article for article in converted if article.published >= since]


def _to_article(source: Source, entry: Any, since: datetime) -> Article:
    link = entry.get("link", "")
    return Article(
        id=entry.get("id") or link,
        source=source.name,
        title=entry.get("title", ""),
        text=_clean_text(entry.get("summary", "")),
        url=link,
        published=_published_or(entry, since),
    )


def _published_or(entry: Any, fallback: datetime) -> datetime:
    parsed_time = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed_time is None:
        return fallback
    return datetime(*parsed_time[:6], tzinfo=timezone.utc)


def _clean_text(raw_html: str) -> str:
    without_tags = _TAG_PATTERN.sub("", raw_html)
    return " ".join(without_tags.split())[:TEXT_MAX_CHARS]
