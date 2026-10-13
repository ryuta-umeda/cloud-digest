import json
import logging
import re
import time
from collections.abc import Callable
from typing import Protocol

from digest.models import Article, DigestItem

logger = logging.getLogger(__name__)

DEFAULT_MAX_ITEMS = 5
MAX_RETRIES = 3
SUMMARY_MAX_CHARS = 200
HEADLINE_MAX_CHARS = 40
# Characters that let an LLM-written summary forge a second digest item or smuggle in a link.
_FORBIDDEN_IN_SUMMARY = ("http", "://", "■", "→")
# HTTP codes meaning "our configuration is wrong": retrying or degrading silently would hide it.
_CONFIG_ERROR_CODES = frozenset({400, 401, 403, 404})
INITIAL_BACKOFF_SECONDS = 1.0
_CODE_FENCE_PATTERN = re.compile(r"^```(?:json)?\s*|\s*```$")


class LlmConfigError(Exception):
    """Bad API key, wrong model name, etc. Never retried and never papered over by the fallback."""


class LlmClient(Protocol):
    def generate(self, prompt: str) -> str: ...


class GeminiClient:
    """Thin adapter over google-genai; exercised by the workflow smoke test, not unit tests."""

    def __init__(self, api_key: str, model: str):
        from google import genai

        self._client = genai.Client(api_key=api_key)
        self._model = model

    def generate(self, prompt: str) -> str:
        from google.genai import errors

        try:
            response = self._client.models.generate_content(model=self._model, contents=prompt)
        except errors.APIError as error:
            if error.code in _CONFIG_ERROR_CODES:
                raise LlmConfigError(f"Gemini rejected the request ({error.code}): {error}") from error
            raise
        return response.text or ""


def summarize(
    articles: list[Article],
    llm: LlmClient,
    max_items: int = DEFAULT_MAX_ITEMS,
    sleep: Callable[[float], None] = time.sleep,
) -> list[DigestItem]:
    """Pick up to `max_items` articles and summarize them in Japanese.

    Any LLM failure (exception, non-JSON, no usable item) is retried with exponential
    backoff; when every attempt fails the digest degrades to title + link only.
    """
    if not articles:
        return []
    prompt = _build_prompt(articles, max_items)
    backoff = INITIAL_BACKOFF_SECONDS
    for attempt in range(MAX_RETRIES + 1):
        try:
            items = _parse_reply(llm.generate(prompt), articles, max_items)
            if items:
                return items
        except LlmConfigError:
            raise
        except Exception as error:
            logger.warning("LLM attempt %d failed: %s", attempt + 1, error)
        if attempt < MAX_RETRIES:
            sleep(backoff)
            backoff *= 2
    return _fallback_items(articles, max_items)


def _build_prompt(articles: list[Article], max_items: int) -> str:
    listing = "\n".join(
        f"- 出典: {a.source}\n  タイトル: {a.title}\n  URL: {a.url}\n  本文冒頭: {a.text}" for a in articles
    )
    return (
        f"以下はクラウド関連の新着記事です。読者の関心が高そうなものを最大{max_items}件選び、"
        "それぞれ日本語で2〜3行に要約し、30字以内の日本語の見出しも付けてください。\n"
        "禁止: 記事にない情報の追加。断定的な推奨。\n"
        '出力は JSON 配列のみ。各要素は {"url": 記事のURL, "headline": 見出し, "summary": 要約} とし、url は下記の記事のものだけを使うこと。\n\n'
        f"{listing}"
    )


def _parse_reply(reply: str, articles: list[Article], max_items: int) -> list[DigestItem]:
    by_url = {article.url: article for article in articles}
    raw_items = json.loads(_CODE_FENCE_PATTERN.sub("", reply.strip()))
    if not isinstance(raw_items, list):
        raise ValueError("LLM reply is not a JSON array")
    items: list[DigestItem] = []
    seen_urls: set[str] = set()
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        url = raw.get("url")
        summary = _clean_summary(raw.get("summary"))
        if url not in by_url or url in seen_urls or summary is None:
            continue
        seen_urls.add(url)
        article = by_url[url]
        headline = _clean_line(raw.get("headline"), HEADLINE_MAX_CHARS) or ""
        items.append(DigestItem(article.source, article.title, summary, article.url, headline))
    return items[:max_items]


def _clean_summary(raw_summary: object) -> str | None:
    """Return a one-line, length-capped summary, or None when it looks like an injected post."""
    return _clean_line(raw_summary, SUMMARY_MAX_CHARS)


def _clean_line(raw_text: object, max_chars: int) -> str | None:
    if not isinstance(raw_text, str):
        return None
    text = " ".join(raw_text.split())
    if not text or any(token in text for token in _FORBIDDEN_IN_SUMMARY):
        return None
    return text[:max_chars]


def _fallback_items(articles: list[Article], max_items: int) -> list[DigestItem]:
    """Newest first, interleaved across sources so one chatty feed cannot crowd out the rest."""
    queues: dict[str, list[Article]] = {}
    for article in sorted(articles, key=lambda a: a.published, reverse=True):
        queues.setdefault(article.source, []).append(article)
    picked: list[Article] = []
    while len(picked) < max_items and any(queues.values()):
        for queue in queues.values():
            if queue and len(picked) < max_items:
                picked.append(queue.pop(0))
    return [DigestItem(a.source, a.title, "", a.url) for a in picked]
