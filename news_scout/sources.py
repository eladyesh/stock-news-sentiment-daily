"""Broad discovery, public-source follow-up, and an honest coverage ledger."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
import json
import re
from urllib.parse import urlencode, urljoin
import xml.etree.ElementTree as ET

from .core import Article, PageText, clean, domain, iso, timestamp, words
from .http import error_label


def rss_url(query: str) -> str:
    return "https://news.google.com/rss/search?" + urlencode(
        {"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"})


def parse_feed(data: bytes, collector: str, family: str) -> list[Article]:
    root = ET.fromstring(data)
    result = []
    atom = "{http://www.w3.org/2005/Atom}"
    nodes = root.findall(".//item") or root.findall(f"{atom}entry")
    for node in nodes:
        def value(tag):
            return node.findtext(tag) or node.findtext(atom + tag) or ""
        url = value("link")
        if not url:
            links = node.findall(atom + "link")
            url = next((x.get("href", "") for x in links if x.get("rel", "alternate") == "alternate"), "")
        published = value("pubDate") or value("published") or value("updated")
        date = timestamp(published)
        if not url.startswith(("https://", "http://")) or date is None:
            continue
        publisher = value("source") or domain(url)
        text = clean(value("description") or value("summary") or value("content"))
        author_node = node.find(atom + "author")
        author = author_node.findtext(atom + "name", "") if author_node is not None else value("author")
        result.append(Article(clean(value("title")), url, iso(date), text[:2500], collector,
                              family, publisher, author,
                              evidence="unverified social claim" if family == "social" else "unverified lead"))
    return result


def parse_gdelt(data: dict, collector: str) -> list[Article]:
    rows = []
    for row in data.get("articles", []):
        dt = timestamp(row.get("seendate", ""))
        if not dt or row.get("language", "English") != "English":
            continue
        rows.append(Article(clean(row.get("title", "")), row.get("url", ""), iso(dt),
                            collector=collector, publisher=row.get("domain", ""),
                            timestamp_basis="GDELT first seen; publication/event time unverified"))
    return rows


def parse_bluesky(data: dict, collector: str) -> list[Article]:
    rows = []
    for post in data.get("posts", []):
        record = post.get("record", {})
        dt = timestamp(record.get("createdAt", ""))
        languages = record.get("langs", [])
        if not dt or (languages and "en" not in languages):
            continue
        uri = post.get("uri", "")
        parts = uri.split("/")
        if len(parts) < 5:
            continue
        # Use the DID, avoiding impersonation-by-display-name when constructing links.
        url = f"https://bsky.app/profile/{parts[2]}/post/{parts[-1]}"
        text = clean(record.get("text", ""))
        rows.append(Article(text[:300], url, iso(dt), text, collector, "social", "bsky.app",
                            post.get("author", {}).get("did", ""),
                            evidence="unverified social claim", languages=languages))
    return rows


class Collector:
    def __init__(self, client, config: dict, now: datetime):
        self.client, self.config, self.now = client, config, now
        self.coverage: list[dict] = []
        self.page_reads: list[dict] = []

    def execute(self, tasks: list[dict], *, stage: str) -> list[Article]:
        result: list[Article] = []

        def run(task):
            name = task["name"]
            try:
                if task["kind"] == "rss":
                    raw = parse_feed(self.client.get(task["url"])[0], name, task["family"])
                elif task["kind"] == "gdelt":
                    raw = parse_gdelt(self.client.json(task["url"]), name)
                else:
                    raw = parse_bluesky(self.client.json(task["url"]), name)
                cutoff = self.now - timedelta(hours=self.config["window_hours"])
                fresh = [a for a in raw if cutoff <= timestamp(a.published_at) <= self.now]
                for a in fresh:
                    a.retrieved_at = iso(self.now)
                limit = task.get("limit", 100)
                return fresh, {"source": name, "stage": stage, "family": task["family"],
                               "status": "ok", "returned": len(raw), "in_window": len(fresh),
                               "possibly_capped": len(raw) >= limit, "url": task["url"]}
            except Exception as exc:
                return [], {"source": name, "stage": stage, "family": task["family"],
                            "status": "unavailable", "returned": 0, "in_window": 0,
                            "reason": error_label(exc), "url": task["url"]}

        with ThreadPoolExecutor(max_workers=self.config["workers"]) as pool:
            futures = [pool.submit(run, task) for task in tasks]
            for future in as_completed(futures):
                articles, status = future.result()
                result.extend(articles)
                self.coverage.append(status)
        return result

    def discover(self, *, smoke: bool = False) -> list[Article]:
        tasks = []
        for i, query in enumerate(self.config["google_news_queries"]):
            tasks.append({"name": f"google-news:{i}", "kind": "rss", "family": "news",
                          "url": rss_url(query + " when:1d"), "limit": 100})
        for i, query in enumerate(self.config["gdelt_queries"]):
            params = {"query": query + " sourcelang:english", "mode": "artlist", "format": "json",
                      "maxrecords": 250, "sort": "datedesc", "timespan": "24h"}
            tasks.append({"name": f"gdelt:{i}", "kind": "gdelt", "family": "news",
                          "url": "https://api.gdeltproject.org/api/v2/doc/doc?" + urlencode(params), "limit": 250})
        for sub in self.config["reddit_communities"]:
            tasks.append({"name": f"reddit:{sub}", "kind": "rss", "family": "social",
                          "url": f"https://www.reddit.com/r/{sub}/new/.rss?limit=100", "limit": 100})
        for i, query in enumerate(self.config["bluesky_queries"]):
            params = {"q": query, "lang": "en", "sort": "latest", "limit": 100,
                      "since": iso(self.now - timedelta(hours=24))}
            tasks.append({"name": f"bluesky:{i}", "kind": "bluesky", "family": "social",
                          "url": "https://public.api.bsky.app/xrpc/app.bsky.feed.searchPosts?" + urlencode(params), "limit": 100})
        for feed in self.config["feeds"]:
            tasks.append(dict(feed, kind="rss"))
        if smoke:
            tasks = [x for x in tasks if x["name"] in {"google-news:0", "google-news:1", "reddit:stocks", "gdelt:0"}]
        return self.execute(tasks, stage="discovery")

    def follow_up(self, candidates: list[tuple[str, str]], *, smoke: bool = False) -> list[Article]:
        tasks = []
        for ticker, name in candidates[:2 if smoke else self.config["followup_stocks"]]:
            name = name.replace('"', "")
            searches = {
                "original": f'"{name}" (announces OR results OR guidance OR agreement OR approval) when:1d',
                "contrary": f'"{name}" (denies OR correction OR investigation OR risks OR downgrade OR misleading) when:1d',
            }
            for kind, query in searches.items():
                tasks.append({"name": f"followup:{ticker}:{kind}", "kind": "rss", "family": "news",
                              "url": rss_url(query), "limit": 100})
        return self.execute(tasks, stage="follow-up")

    def read_pages(self, articles: list[Article]) -> None:
        """Read a bounded finalist set. Search snippets never become verified facts."""
        primary_hosts = {"sec.gov", "fda.gov", "justice.gov", "ftc.gov", "whitehouse.gov"}
        release_hosts = {"businesswire.com", "globenewswire.com", "prnewswire.com", "accessnewswire.com"}

        def read(article):
            if article.family == "social":
                return {"url": article.url, "status": "skipped social post"}
            status = {"url": article.url, "status": "excerpt only"}
            try:
                data, final_url, mime = self.client.get(article.url)
                if "html" not in mime:
                    return dict(status, reason="not an HTML publisher page")
                # Google News is discovery; following it to another Google page isn't an original read.
                if domain(final_url) in {"news.google.com", "consent.google.com"}:
                    return dict(status, reason="aggregator did not expose an original publisher page")
                page = PageText()
                page.feed(data.decode("utf-8", "replace"))
                body = page.text
                anchors = set(words(article.title)) - {"the", "and", "for", "with", "from", "stock", "shares", "news"}
                overlap = len(anchors & set(words(body))) / max(len(anchors), 1)
                if len(body) < 350 or overlap < 0.5:
                    return dict(status, reason="insufficient matching article text")
                if re.search(r"verify (you are|that you are) human|checking your browser|access denied", body[:1500], re.I):
                    return dict(status, reason="publisher access challenge")
                article.read_status = "publisher page read"
                article.url = final_url
                # Do not replace the classifier's source excerpt with unrelated navigation text.
                host = domain(final_url)
                if any(host == h or host.endswith("." + h) for h in primary_hosts):
                    article.evidence = "official disclosure read; claim requires context"
                elif any(host == h or host.endswith("." + h) for h in release_hosts):
                    article.evidence = "company release read; issuer claim"
                else:
                    article.evidence = "publisher report read; attributed claim"
                return dict(status, status="publisher page read", final_url=final_url)
            except Exception as exc:
                return dict(status, reason=error_label(exc))

        with ThreadPoolExecutor(max_workers=self.config["workers"]) as pool:
            self.page_reads.extend(pool.map(read, articles[:self.config["page_read_limit"]]))
