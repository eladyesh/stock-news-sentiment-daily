"""Small data types and provenance-preserving normalization."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import html
from html.parser import HTMLParser
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

UTC = timezone.utc


def timestamp(value: str) -> datetime | None:
    if not value:
        return None
    for parser in (lambda x: datetime.fromisoformat(x.replace("Z", "+00:00")),
                   parsedate_to_datetime,
                   lambda x: datetime.strptime(x, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)):
        try:
            dt = parser(value)
            if dt.tzinfo is not None:
                return dt.astimezone(UTC)
        except (ValueError, TypeError, OverflowError):
            continue
    return None


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat()


def clean(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]*>", " ", value))).strip()


def words(value: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", value.lower())


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:24]


def canonical_url(url: str) -> str:
    p = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
             if not k.lower().startswith("utm_") and k.lower() not in
             {"fbclid", "gclid", "guccounter", "guce_referrer", "ref", "source"}]
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path, urlencode(query), ""))


def domain(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


@dataclass
class Article:
    title: str
    url: str
    published_at: str
    text: str = ""
    collector: str = ""
    family: str = "news"
    publisher: str = ""
    author: str = ""
    timestamp_basis: str = "publisher publication time"
    read_status: str = "feed excerpt only"
    evidence: str = "unverified lead"
    retrieved_at: str = ""
    event_at: str | None = None
    tickers: list[str] = field(default_factory=list)
    score: float | None = None
    tone: str = "unscored"
    probability: float | None = None
    languages: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        return digest(canonical_url(self.url))

    def metadata(self) -> dict:
        # Do not archive article bodies or social profiles in the repository.
        row = asdict(self)
        row.pop("text", None)
        row.pop("author", None)
        return row


class PageText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "nav", "footer", "noscript"}:
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style", "nav", "footer", "noscript"}:
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden and data.strip():
            self.parts.append(data.strip())

    @property
    def text(self):
        return clean(" ".join(self.parts))
