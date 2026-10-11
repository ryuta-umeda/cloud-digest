import json
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from functools import partial
from pathlib import Path

import feedparser

from digest.main import JobConfig, run
from digest.render import validate_atom
from digest.state import load_entries
from digest.summarize import summarize

NOW = datetime(2026, 10, 12, 8, 17, tzinfo=timezone(timedelta(hours=9)))
FEED_URL = "https://example.github.io/cloud-digest/digest.xml"


def _rss(*items: tuple[str, str], pub: str = "Sun, 11 Oct 2026 23:00:00 GMT") -> str:
    body = "".join(
        f"<item><title>{t}</title><link>{u}</link><guid>{u}</guid>"
        f"<pubDate>{pub}</pubDate><description>d</description></item>"
        for t, u in items
    )
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>x</title>{body}</channel></rss>'


class FakeLlm:
    def __init__(self, reply=None, error: Exception | None = None):
        self._reply, self._error = reply, error

    def generate(self, prompt: str) -> str:
        if self._error:
            raise self._error
        return self._reply


def _config(tmp_path: Path) -> JobConfig:
    sources = tmp_path / "sources.yml"
    sources.write_text("sources:\n  - name: AWS\n    url: https://feed/1\n", encoding="utf-8")
    return JobConfig(sources_path=sources, output_dir=tmp_path, feed_url=FEED_URL)


def _parse(feed_text: str):
    return lambda url: feedparser.parse(feed_text)


def _summarizer(llm: FakeLlm):
    return partial(summarize, llm=llm, sleep=lambda seconds: None)


GOOD_REPLY = json.dumps([{"url": "https://e/1", "summary": "要約1"}], ensure_ascii=False)
FEED = _rss(("Title 1", "https://e/1"), ("Title 2", "https://e/2"))


def test_run_writes_valid_digest_xml(tmp_path):
    run(NOW, _config(tmp_path), _summarizer(FakeLlm(GOOD_REPLY)), _parse(FEED))
    xml = (tmp_path / "digest.xml").read_text(encoding="utf-8")
    validate_atom(xml)
    assert "digest-2026-10-12" in xml and "要約1" in xml


def test_run_twice_same_day_keeps_single_entry(tmp_path):
    config, summarizer = _config(tmp_path), _summarizer(FakeLlm(GOOD_REPLY))
    run(NOW, config, summarizer, _parse(FEED))
    first_xml = (tmp_path / "digest.xml").read_text(encoding="utf-8")
    run(NOW + timedelta(minutes=5), config, summarizer, _parse(FEED))
    assert len(load_entries(tmp_path / "entries.json")) == 1
    assert (tmp_path / "digest.xml").read_text(encoding="utf-8") == first_xml


def test_run_with_no_articles_adds_no_entry_but_updates_last_run(tmp_path):
    run(NOW, _config(tmp_path), _summarizer(FakeLlm(GOOD_REPLY)), _parse(_rss()))
    assert load_entries(tmp_path / "entries.json") == []
    validate_atom((tmp_path / "digest.xml").read_text(encoding="utf-8"))
    seen = json.loads((tmp_path / "seen.json").read_text(encoding="utf-8"))
    assert seen["last_run"] == NOW.isoformat()


def test_run_with_llm_failure_still_writes_fallback_digest(tmp_path):
    run(NOW, _config(tmp_path), _summarizer(FakeLlm(error=RuntimeError("429"))), _parse(FEED))
    xml = (tmp_path / "digest.xml").read_text(encoding="utf-8")
    validate_atom(xml)
    assert "■ AWS｜Title 1" in xml and "要約：" not in xml


def test_run_keeps_only_latest_14_entries(tmp_path):
    config = _config(tmp_path)
    for day in range(16):
        run_time = NOW + timedelta(days=day)
        feed = _rss((f"Title {day}", f"https://e/{day}"), pub=format_datetime(run_time - timedelta(hours=1)))
        reply = json.dumps([{"url": f"https://e/{day}", "summary": "s"}])
        run(run_time, config, _summarizer(FakeLlm(reply)), _parse(feed))
    assert len(load_entries(tmp_path / "entries.json")) == 14


def test_run_picks_up_articles_published_over_the_weekend(tmp_path):
    # Monday run must still see Friday-evening / weekend posts: the job only runs on weekdays.
    monday = datetime(2026, 10, 12, 8, 17, tzinfo=timezone(timedelta(hours=9)))
    feed = _rss(("Weekend news", "https://e/1"), pub=format_datetime(monday - timedelta(hours=60)))
    run(monday, _config(tmp_path), _summarizer(FakeLlm(GOOD_REPLY)), _parse(feed))
    assert len(load_entries(tmp_path / "entries.json")) == 1
