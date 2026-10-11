from pathlib import Path

import pytest

from digest.models import Source
from digest.sources import load_sources


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "sources.yml"
    path.write_text(text, encoding="utf-8")
    return path


def test_load_sources_returns_sources(tmp_path):
    path = _write(
        tmp_path,
        "sources:\n  - name: AWS What's New\n    url: https://aws.amazon.com/about-aws/whats-new/recent/feed/\n",
    )
    assert load_sources(path) == [
        Source(name="AWS What's New", url="https://aws.amazon.com/about-aws/whats-new/recent/feed/")
    ]


def test_load_sources_rejects_missing_url(tmp_path):
    path = _write(tmp_path, "sources:\n  - name: NoUrl\n")
    with pytest.raises(ValueError):
        load_sources(path)


def test_load_sources_rejects_non_http_url(tmp_path):
    path = _write(tmp_path, "sources:\n  - name: Bad\n    url: file:///etc/passwd\n")
    with pytest.raises(ValueError):
        load_sources(path)
