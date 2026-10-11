import json
from datetime import datetime, timezone

from digest.models import Article, DigestItem
import pytest

from digest.summarize import LlmConfigError, summarize

NOW = datetime(2026, 10, 12, 8, 17, tzinfo=timezone.utc)


def _articles(count: int) -> list[Article]:
    return [Article(f"id{i}", "AWS", f"title{i}", f"text{i}", f"https://e/{i}", NOW) for i in range(count)]


class FakeLlm:
    """Returns scripted responses in order; an Exception instance is raised instead."""

    def __init__(self, responses: list[object]):
        self._responses = list(responses)
        self.calls = 0

    def generate(self, prompt: str) -> str:
        self.calls += 1
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return str(response)


def _reply(*indexes: int) -> str:
    return json.dumps([{"url": f"https://e/{i}", "summary": f"要約{i}"} for i in indexes], ensure_ascii=False)


def _no_sleep(waits: list[float]):
    return lambda seconds: waits.append(seconds)


def test_summarize_returns_parsed_items():
    items = summarize(_articles(3), FakeLlm([_reply(2, 0)]), sleep=_no_sleep([]))
    assert items == [
        DigestItem("AWS", "title2", "要約2", "https://e/2"),
        DigestItem("AWS", "title0", "要約0", "https://e/0"),
    ]


def test_summarize_drops_url_not_in_input():
    reply = json.dumps(
        [{"url": "https://evil/x", "summary": "幻覚"}, {"url": "https://e/1", "summary": "要約1"}],
        ensure_ascii=False,
    )
    items = summarize(_articles(3), FakeLlm([reply]), sleep=_no_sleep([]))
    assert [i.url for i in items] == ["https://e/1"]


def test_summarize_truncates_to_max_items():
    items = summarize(_articles(8), FakeLlm([_reply(0, 1, 2, 3, 4, 5, 6)]), sleep=_no_sleep([]))
    assert len(items) == 5


def test_summarize_accepts_json_code_fence():
    fenced = "```json\n" + _reply(1) + "\n```"
    items = summarize(_articles(2), FakeLlm([fenced]), sleep=_no_sleep([]))
    assert [i.url for i in items] == ["https://e/1"]


def test_summarize_retries_then_succeeds():
    waits: list[float] = []
    llm = FakeLlm([RuntimeError("429"), RuntimeError("429"), _reply(0)])
    items = summarize(_articles(2), llm, sleep=_no_sleep(waits))
    assert [i.summary for i in items] == ["要約0"]
    assert waits == [1, 2]


def test_summarize_falls_back_after_all_retries_fail():
    waits: list[float] = []
    llm = FakeLlm([RuntimeError("429")] * 4)
    items = summarize(_articles(7), llm, sleep=_no_sleep(waits))
    assert llm.calls == 4
    assert waits == [1, 2, 4]
    assert [i.summary for i in items] == [""] * 5
    assert items[0] == DigestItem("AWS", "title0", "", "https://e/0")


def test_summarize_falls_back_on_non_json():
    llm = FakeLlm(["すみません、できません"] * 4)
    items = summarize(_articles(2), llm, sleep=_no_sleep([]))
    assert [i.summary for i in items] == ["", ""]


def test_summarize_with_no_articles_skips_llm():
    llm = FakeLlm([])
    assert summarize([], llm, sleep=_no_sleep([])) == []
    assert llm.calls == 0


@pytest.mark.parametrize("bad_summary", ["詳細は http://evil.example へ", "see ://x", "行1\n■ 偽｜偽記事\n→ https://evil.example/login", "→ 次へ"])
def test_summarize_drops_summary_that_could_forge_a_post(bad_summary):
    reply = json.dumps(
        [{"url": "https://e/0", "summary": bad_summary}, {"url": "https://e/1", "summary": "安全な要約"}],
        ensure_ascii=False,
    )
    items = summarize(_articles(2), FakeLlm([reply]), sleep=_no_sleep([]))
    assert [i.url for i in items] == ["https://e/1"]


def test_summarize_collapses_whitespace_and_caps_length():
    reply = json.dumps([{"url": "https://e/0", "summary": "行1\n行2  " + "あ" * 300}], ensure_ascii=False)
    items = summarize(_articles(1), FakeLlm([reply]), sleep=_no_sleep([]))
    assert "\n" not in items[0].summary
    assert items[0].summary.startswith("行1 行2 ")
    assert len(items[0].summary) == 200


def test_summarize_reraises_config_error_without_retry():
    llm = FakeLlm([LlmConfigError("invalid API key")])
    with pytest.raises(LlmConfigError):
        summarize(_articles(2), llm, sleep=_no_sleep([]))
    assert llm.calls == 1


def test_fallback_spreads_across_sources_newest_first():
    older = datetime(2026, 10, 11, tzinfo=timezone.utc)
    aws = [Article(f"a{i}", "AWS", f"aws{i}", "x", f"https://e/a{i}", NOW) for i in range(6)]
    azure = [Article("z0", "Azure", "azure0", "x", "https://e/z0", older)]
    items = summarize(aws + azure, FakeLlm([RuntimeError("429")] * 4), sleep=_no_sleep([]))
    assert len(items) == 5
    assert "azure0" in [i.title for i in items]
