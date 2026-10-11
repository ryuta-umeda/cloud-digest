from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Source:
    name: str
    url: str


@dataclass(frozen=True)
class Article:
    id: str
    source: str
    title: str
    text: str
    url: str
    published: datetime


@dataclass(frozen=True)
class DigestItem:
    source: str
    title: str
    summary: str  # "" means LLM fallback: render title and link only
    url: str


@dataclass(frozen=True)
class DigestEntry:
    id: str
    title: str
    published: datetime
    body: str
