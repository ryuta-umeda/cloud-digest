import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from digest.models import Article

SEEN_RETENTION_DAYS = 30


@dataclass(frozen=True)
class SeenState:
    last_run: datetime | None
    seen: dict[str, date]


def load_seen(path: Path) -> SeenState:
    if not path.exists():
        return SeenState(last_run=None, seen={})
    raw = json.loads(path.read_text(encoding="utf-8"))
    last_run = raw.get("last_run")
    return SeenState(
        last_run=datetime.fromisoformat(last_run) if last_run else None,
        seen={article_id: date.fromisoformat(day) for article_id, day in raw.get("seen", {}).items()},
    )


def save_seen(state: SeenState, path: Path) -> None:
    payload = {
        "last_run": state.last_run.isoformat() if state.last_run else None,
        "seen": {article_id: day.isoformat() for article_id, day in sorted(state.seen.items())},
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def filter_unseen(articles: list[Article], state: SeenState) -> list[Article]:
    return [article for article in articles if article.id not in state.seen]


def mark_seen(state: SeenState, articles: list[Article], now: datetime) -> SeenState:
    cutoff = now.date() - timedelta(days=SEEN_RETENTION_DAYS)
    kept = {article_id: day for article_id, day in state.seen.items() if day >= cutoff}
    kept.update({article.id: now.date() for article in articles})
    return SeenState(last_run=now, seen=kept)
