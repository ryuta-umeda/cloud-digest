from pathlib import Path

import yaml

from digest.models import Source

_ALLOWED_SCHEMES = ("http://", "https://")


def load_sources(path: Path) -> list[Source]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    entries = raw.get("sources") if isinstance(raw, dict) else None
    if not isinstance(entries, list):
        raise ValueError("sources.yml must contain a 'sources' list")
    return [_parse_source(entry) for entry in entries]


def _parse_source(entry: object) -> Source:
    if not isinstance(entry, dict):
        raise ValueError(f"source entry must be a mapping: {entry!r}")
    name, url = entry.get("name"), entry.get("url")
    if not isinstance(name, str) or not name:
        raise ValueError(f"source is missing 'name': {entry!r}")
    if not isinstance(url, str) or not url.startswith(_ALLOWED_SCHEMES):
        raise ValueError(f"source '{name}' needs an http(s) 'url': {url!r}")
    return Source(name=name, url=url)
