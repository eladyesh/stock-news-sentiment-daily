"""Evidence-aware sentiment and transparent research-priority ranking."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
import math
import re
from statistics import mean

from .core import Article, canonical_url, digest, domain, timestamp, words

CATALYSTS = [
    ("guidance", 30, r"guidance|outlook|forecast|profit warning",
     "A change in expected revenue or earnings could alter the investment case. Compare the new outlook with prior guidance and dated consensus.",
     "The change may already be priced in, temporary, or based on a different accounting measure."),
    ("clinical / regulatory", 30, r"fda|phase [123i]|clinical|drug approval|trial results",
     "A clinical or regulatory milestone could change commercialization prospects. Read the actual endpoint, safety data and regulatory conditions.",
     "Headline results may not establish commercial approval, efficacy across endpoints, or sufficient cash runway."),
    ("transaction", 28, r"acquisition|acquires|merger|takeover|buyout",
     "A corporate transaction could create a new valuation or event-driven research case. Establish terms, financing and which company is the buyer.",
     "An unconfirmed proposal, financing gap, regulatory review or a low closing probability can undermine the case."),
    ("commercial catalyst", 26, r"contract|partnership|backlog|purchase order|supply agreement|design win|capacity arrangement|capacity expansion",
     "New commercial activity could affect future revenue or margins. Check binding value, duration, incremental revenue and profitability.",
     "A partnership announcement may contain no committed revenue; contract value need not equal profit or near-term cash."),
    ("earnings", 24, r"earnings|\bearn(?:s|ed)\b|quarter(?:ly)?.{0,35}results|revenue|net income|operating profit",
     "The earnings update may change expectations. Reconcile margins, cash conversion and guidance with comparable prior periods.",
     "Year-over-year growth does not prove a consensus beat, and one-offs or working capital can weaken reported earnings."),
    ("capital structure", 22, r"offering|dilution|buyback|repurchase|refinanc|bankruptcy|restructur",
     "A financing or capital-allocation event could change per-share economics. Reconcile cash raised, debt, new shares and financing needs.",
     "Dilution, distress, restrictive terms or an unexecuted buyback authorization can offset an apparently positive headline."),
    ("legal / operational", 22, r"investigation|lawsuit|recall|regulator|fraud|production|supply shortage",
     "A legal or operating development may change expected costs, supply or competitive position. Check the original authority or company disclosure.",
     "Allegations are not findings; the financial effect and resolution timeline may remain unknown."),
    ("analyst expectations", 12, r"upgrade|downgrade|price target|analyst",
     "A changed analyst view is a lead to investigate the underlying assumptions and whether it reflects new evidence.",
     "An analyst opinion is not a transaction or independent proof of business improvement."),
]


def routine_notice(article: Article) -> bool:
    """Keep calendar notices and shareholder-solicitation ads out of the shortlist."""
    return bool(re.search(
        r"(?:to|will) (?:report|release|announce).{0,45}(?:results|earnings)|"
        r"(?:announces|sets).{0,35}(?:earnings|conference call).{0,20}(?:date|schedule)|"
        r"(?:to|will) (?:participate|highlight|showcase|host).{0,160}(?:conference|meeting|summit|investor day)|"
        r"hiring event|job fair|career fair|"
        r"(?:shareholder|investor|class action).{0,40}(?:deadline|alert|reminder)|"
        r"(?:law (?:firm|offices)|llp).{0,60}(?:investigat|remind|announc)|"
        r"(?:remind|alert).{0,40}(?:investors|shareholders).{0,40}(?:deadline|lawsuit)",
        article.title, re.I))


def catalyst(article: Article):
    # Company-description boilerplate in a feed often mentions contracts/revenue
    # unrelated to the actual event. Require the catalyst to appear in the headline.
    content = article.title
    return next((row for row in CATALYSTS if re.search(row[2], content, re.I)),
                ("attention", 5, "", "Investigate the reason for new attention before forming an investment thesis.",
                 "Attention alone does not establish improving economics or attractive valuation."))


def headline_key(article: Article) -> str:
    title = re.sub(r"\s+[|–—]\s+.*$", "", article.title)
    return digest(" ".join(words(title)))


def deduplicate(articles: list[Article]) -> list[Article]:
    by_url: dict[str, Article] = {}
    for article in articles:
        key = canonical_url(article.url)
        existing = by_url.get(key)
        if existing is None:
            by_url[key] = article
        else:
            # Prefer a publisher timestamp over an aggregator's first-seen timestamp.
            if "first seen" in existing.timestamp_basis and "first seen" not in article.timestamp_basis:
                article.text = max((article.text, existing.text), key=len)
                by_url[key] = article
            elif len(article.text) > len(existing.text):
                existing.text = article.text
    return list(by_url.values())


def story_groups(articles: list[Article]) -> list[list[Article]]:
    groups: list[list[Article]] = []
    buckets: dict[tuple, list[int]] = defaultdict(list)
    stop = {"the", "a", "an", "and", "of", "in", "to", "for", "on", "with", "at", "as", "by"}
    for a in articles:
        tokens = set(words(a.title)) - stop
        # Preserve changed numbers, negation and direction when clustering rewrites.
        critical = {x for x in tokens if x.isdigit() or x in
                    {"not", "denies", "raises", "cuts", "lower", "higher", "falls", "rises", "miss", "beats"}}
        bucket = (tuple(a.tickers), a.family)
        found = None
        for i in buckets[bucket]:
            b = groups[i][0]
            other = set(words(b.title)) - stop
            other_critical = {x for x in other if x.isdigit() or x in
                              {"not", "denies", "raises", "cuts", "lower", "higher", "falls", "rises", "miss", "beats"}}
            if critical == other_critical and len(tokens & other) / max(1, len(tokens | other)) >= 0.78:
                found = i
                break
        if found is None:
            buckets[bucket].append(len(groups))
            groups.append([a])
        else:
            groups[found].append(a)
    return groups


class FinancialSentiment:
    """Local CPU inference; never calls a paid or hosted inference API."""
    def __init__(self, config):
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
        from langdetect import DetectorFactory
        DetectorFactory.seed = 0
        self.torch = torch
        torch.set_num_threads(2)
        args = {"revision": config["model_revision"], "trust_remote_code": False}
        self.tokenizer = AutoTokenizer.from_pretrained(config["model"], **args)
        self.model = AutoModelForSequenceClassification.from_pretrained(
            config["model"], use_safetensors=True, **args).eval()
        self.labels = {int(k): v.lower() for k, v in self.model.config.id2label.items()}
        if set(self.labels.values()) != {"positive", "negative", "neutral"}:
            raise ValueError("Unexpected sentiment model labels")

    def apply(self, articles: list[Article]) -> int:
        from langdetect import detect, LangDetectException
        eligible = []
        for a in articles:
            try:
                english = detect(a.title + " " + a.text[:500]) == "en"
            except LangDetectException:
                english = False
            if english:
                eligible.append(a)
        for start in range(0, len(eligible), 24):
            batch = eligible[start:start + 24]
            # Headline and feed context, not thousands of unrelated page/navigation words.
            encoded = self.tokenizer([a.title + ". " + a.text[:700] for a in batch],
                                     padding=True, truncation=True, max_length=192, return_tensors="pt")
            with self.torch.inference_mode():
                probabilities = self.model(**encoded).logits.softmax(-1).tolist()
            for a, probs in zip(batch, probabilities):
                p = {self.labels[i]: float(v) for i, v in enumerate(probs)}
                a.score = p["positive"] - p["negative"]
                a.tone = max(p, key=p.get)
                a.probability = p[a.tone]
        return len(eligible)


def comparable_baseline(state, ticker, signature, date):
    usable = [x for x in state.get("daily", [])
              if x["date"] < date and x.get("signature") == signature and not x.get("smoke")]
    usable = usable[-7:]
    if len(usable) < 3:
        return None
    counts = [x["stocks"].get(ticker, {}).get("count", 0) for x in usable]
    scored = [x["stocks"].get(ticker, {}) for x in usable]
    total = sum(x.get("count", 0) for x in scored)
    sentiment = sum(x.get("score", 0) * x.get("count", 0) for x in scored) / total if total else None
    return {"days": len(usable), "count": mean(counts), "sentiment": sentiment}


def rank(articles, resolver, state, signature, date, config):
    by_ticker: dict[str, list[Article]] = defaultdict(list)
    for a in articles:
        if a.score is not None and not routine_notice(a):
            for ticker in a.tickers:
                by_ticker[ticker].append(a)
    candidates, snapshot = [], {}
    known = set(state.get("seen_headlines", {}))
    for ticker, rows in by_ticker.items():
        groups = story_groups(rows)
        # One vote per story; ten syndicated versions are not ten confirmations.
        representatives = [max(g, key=lambda a: (a.read_status == "publisher page read", catalyst(a)[1], len(a.text))) for g in groups]
        score = mean(a.score for a in representatives)
        # Adaptive follow-up targets change daily; exclude them from trend baselines.
        broad_groups = story_groups([a for a in rows if not a.collector.startswith("followup:")])
        broad_count = len(broad_groups)
        broad_score = mean(mean(a.score for a in g) for g in broad_groups) if broad_groups else None
        snapshot[ticker] = {"count": broad_count, "score": round(broad_score or 0, 5)}
        fresh = [a for a in representatives if headline_key(a) not in known]
        if not fresh:
            continue
        news = [a for a in fresh if a.family == "news"]
        read_news = [a for a in news if a.read_status == "publisher page read"]
        lead = max(read_news or news or fresh, key=lambda a: (catalyst(a)[1], abs(a.score), a.published_at))
        kind, materiality, _, hypothesis, risk = catalyst(lead)
        social = [a for a in representatives if a.family == "social"]
        news_sample = [a for a in representatives if a.family == "news"]
        news_tone = mean(a.score for a in news_sample) if news_sample else None
        social_tone = mean(a.score for a in social) if social else None
        baseline = comparable_baseline(state, ticker, signature, date)
        acceleration = broad_count / baseline["count"] if baseline and baseline["count"] > 0 else None
        shift = broad_score - baseline["sentiment"] if broad_score is not None and baseline and baseline["sentiment"] is not None else None
        disagreement = (news_tone is not None and social_tone is not None and len(social) >= 3
                        and news_tone * social_tone < 0 and abs(news_tone - social_tone) > .5)
        evidence_points = 20 if "disclosure read" in lead.evidence or "release read" in lead.evidence else (12 if read_news else 0)
        novelty = 10 * len(fresh) / len(representatives)
        attention_points = min(15, 5 * max(0, (acceleration or 1) - 1))
        shift_points = min(15, abs(shift or 0) * 15)
        # Publisher diversity is breadth, never asserted to be independent corroboration.
        priority = materiality + evidence_points + novelty + attention_points + shift_points + (10 if disagreement else 0)
        if kind == "attention" and attention_points + shift_points < 10:
            continue  # An accessible promotional release alone is not an opportunity.
        category = "Sentiment divergence" if disagreement else (
            "Positive catalyst research" if lead.score > .15 else
            "Downside-risk research" if lead.score < -.15 else "Catalyst watch")
        if not read_news:
            category = "Unverified buzz / news lead"
        contrary = [a for a in representatives if a.score * lead.score < -.1]
        confidence = "Medium" if read_news else "Low"
        confidence_reason = ("Source page read; claim context and independent corroboration still require review."
                             if read_news else "Only an excerpt or social claim was accessible.")
        candidates.append({
            "ticker": ticker, "company": resolver.names[ticker], "category": category,
            "priority": round(min(100, priority), 1), "catalyst": kind,
            "lead": lead.metadata(), "hypothesis": hypothesis, "risk": risk,
            "evidence_confidence": confidence, "confidence_reason": confidence_reason,
            "sample_sentiment": round(score, 3), "news_sentiment": news_tone,
            "social_sentiment": social_tone, "stories": len(groups),
            "publishers": len({a.publisher or domain(a.url) for a in rows}),
            "social_posts": len(social), "new_stories": len(fresh),
            "social_authors_known": len({a.author for a in social if a.author}),
            "social_posts_without_author": sum(not a.author for a in social),
            "broad_discovery_stories": broad_count,
            "baseline": baseline, "attention_ratio": acceleration, "sentiment_shift": shift,
            "contrary": [a.metadata() for a in contrary[:2]],
            "sources": [a.metadata() for a in sorted(representatives, key=lambda x: x.published_at, reverse=True)[:4]],
            "limitations": ["Valuation and price reaction have not been established."] +
                (["Multiple companies share some texts; tone may not apply equally to each issuer."]
                 if any(len(a.tickers) > 1 for a in representatives) else []) +
                (["The financial-news classifier is less reliable on sarcasm and social slang."] if social else [])
        })
    candidates.sort(key=lambda x: (-x["priority"], x["ticker"]))
    supported = [c for c in candidates if c["category"] != "Unverified buzz / news lead"
                 and c["priority"] >= config["minimum_research_score"]]
    buzz = [c for c in candidates if c["category"] == "Unverified buzz / news lead"
            and c["priority"] >= config["minimum_research_score"]][:config["max_buzz_stocks"]]
    total = config["max_report_stocks"]
    selected = supported[:total - len(buzz)] + buzz
    return selected, snapshot, candidates
