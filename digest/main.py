import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from digest.fetch import fetch_articles, parse_with_timeout
from digest.models import Article, DigestItem
from digest.render import JST, build_atom, render_entry, validate_atom
from digest.sources import load_sources
from digest.state import filter_unseen, load_entries, load_seen, mark_seen, save_entries, save_seen
from digest.summarize import GeminiClient, summarize

# 72h, not 24h: the job runs on weekdays only, so Monday must reach back over the weekend.
# Overlap between runs is harmless because seen.json drops already-processed articles.
FETCH_WINDOW = timedelta(hours=72)
MAX_ENTRIES = 14


@dataclass(frozen=True)
class JobConfig:
    sources_path: Path
    output_dir: Path
    feed_url: str


def run(
    now: datetime,
    config: JobConfig,
    summarize_articles: Callable[[list[Article]], list[DigestItem]],
    parse: Callable[[str], Any] = parse_with_timeout,
) -> int:
    """Fetch, summarize and publish one digest. Re-running on the same day is idempotent."""
    articles, failed_sources = fetch_articles(load_sources(config.sources_path), now - FETCH_WINDOW, parse)
    for name in failed_sources:
        print(f"WARNING: failed to fetch source: {name}", file=sys.stderr)

    seen_path = config.output_dir / "seen.json"
    entries_path = config.output_dir / "entries.json"
    state = load_seen(seen_path)
    fresh_articles = filter_unseen(articles, state)

    entries = load_entries(entries_path)
    today = now.astimezone(JST).date()
    # Today's entry is published once. Replacing it after Power Automate posted it would drop
    # the morning's articles; new ones are left unseen and roll into tomorrow's digest.
    if any(entry.id == f"digest-{today.isoformat()}" for entry in entries):
        fresh_articles = []

    items = summarize_articles(fresh_articles)
    if items:
        entries = ([render_entry(items, today)] + entries)[:MAX_ENTRIES]

    atom_xml = build_atom(entries, config.feed_url)
    validate_atom(atom_xml)
    (config.output_dir / "digest.xml").write_text(atom_xml, encoding="utf-8")
    save_entries(entries, entries_path)
    # last_run is saved even on an empty day: the daily commit keeps the repo active (schedule auto-disable).
    save_seen(mark_seen(state, _articles_to_mark_seen(fresh_articles, items), now), seen_path)
    return 0


def _articles_to_mark_seen(fresh_articles: list[Article], items: list[DigestItem]) -> list[Article]:
    """After an LLM selection, unpicked articles are consciously passed over. After the
    title-only fallback nothing was judged, so only what was actually shown counts as seen."""
    used_fallback = any(not item.summary for item in items)
    if not used_fallback:
        return fresh_articles
    shown_urls = {item.url for item in items}
    return [article for article in fresh_articles if article.url in shown_urls]


def main() -> int:
    api_key = os.environ["GEMINI_API_KEY"]
    model = os.environ["GEMINI_MODEL"]
    config = JobConfig(Path("sources.yml"), Path("."), os.environ["FEED_URL"])
    llm = GeminiClient(api_key, model)
    return run(datetime.now(timezone.utc), config, lambda articles: summarize(articles, llm))


if __name__ == "__main__":
    sys.exit(main())
