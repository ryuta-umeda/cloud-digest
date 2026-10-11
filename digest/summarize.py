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
INITIAL_BACKOFF_SECONDS = 1.0
_CODE_FENCE_PATTERN = re.compile(r"^```(?:json)?\s*|\s*```$")


class LlmClient(Protocol):
    def generate(self, prompt: str) -> str: ...


class GeminiClient:
    """Thin adapter over google-genai; exercised by the workflow smoke test, not unit tests."""

    def __init__(self, api_key: str, model: str):
        from google import genai

        self._client = genai.Client(api_key=api_key)
        self._model = model

    def generate(self, prompt: str) -> str:
        response = self._client.models.generate_content(model=self._model, contents=prompt)
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
        "それぞれ日本語で2〜3行に要約してください。\n"
        "禁止: 記事にない情報の追加。断定的な推奨。\n"
        '出力は JSON 配列のみ。各要素は {"url": 記事のURL, "summary": 要約} とし、url は下記の記事のものだけを使うこと。\n\n'
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
        url, summary = raw.get("url"), raw.get("summary")
        if url not in by_url or url in seen_urls or not isinstance(summary, str) or not summary.strip():
            continue
        seen_urls.add(url)
        article = by_url[url]
        items.append(DigestItem(article.source, article.title, summary.strip(), article.url))
    return items[:max_items]


def _fallback_items(articles: list[Article], max_items: int) -> list[DigestItem]:
    return [DigestItem(a.source, a.title, "", a.url) for a in articles[:max_items]]
