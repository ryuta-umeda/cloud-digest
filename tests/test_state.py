import json
from datetime import date, datetime, timezone

from digest.models import Article
from digest.state import SeenState, filter_unseen, load_seen, mark_seen, save_seen

NOW = datetime(2026, 10, 12, 8, 17, tzinfo=timezone.utc)


def _article(article_id: str) -> Article:
    return Article(article_id, "S", "t", "x", f"https://e/{article_id}", NOW)


def test_filter_unseen_drops_seen_ids():
    state = SeenState(last_run=None, seen={"a": date(2026, 10, 11)})
    result = filter_unseen([_article("a"), _article("b")], state)
    assert [a.id for a in result] == ["b"]


def test_mark_seen_prunes_older_than_30_days():
    state = SeenState(last_run=None, seen={"old": date(2026, 9, 1), "recent": date(2026, 10, 1)})
    updated = mark_seen(state, [_article("new")], NOW)
    assert set(updated.seen) == {"recent", "new"}
    assert updated.last_run == NOW


def test_mark_seen_does_not_mutate_input():
    state = SeenState(last_run=None, seen={"a": date(2026, 10, 11)})
    mark_seen(state, [_article("b")], NOW)
    assert state.seen == {"a": date(2026, 10, 11)}
    assert state.last_run is None


def test_load_seen_missing_file_returns_empty(tmp_path):
    assert load_seen(tmp_path / "nope.json") == SeenState(last_run=None, seen={})


def test_save_then_load_roundtrip(tmp_path):
    path = tmp_path / "seen.json"
    state = SeenState(last_run=NOW, seen={"a": date(2026, 10, 11)})
    save_seen(state, path)
    assert json.loads(path.read_text(encoding="utf-8"))["seen"] == {"a": "2026-10-11"}
    assert load_seen(path) == state
