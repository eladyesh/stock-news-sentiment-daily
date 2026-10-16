"""English reports: opportunity hypotheses, evidence and falsifiers."""
from __future__ import annotations

import json
from pathlib import Path


def short_title(title: str) -> str:
    # Keep source quotations short; business interpretations are independently written.
    return " ".join(title.split()[:24]) + (" …" if len(title.split()) > 24 else "")


def render(report: dict) -> list[str]:
    m = report["metrics"]
    mode = "SMOKE CHECK — LIMITED COVERAGE\n" if report["smoke"] else ""
    sections = [
        f"{mode}STOCK NEWS & SENTIMENT OPPORTUNITIES\n{report['date']} | English | US-listed stocks\n"
        f"Window: {report['window_start']} to {report['generated_at']} (UTC).\n\n"
        f"Collected {m['raw_records']} in-window records; {m['unique_articles']} unique URLs; "
        f"{m['unique_publishers']} publisher labels/domains; {m['identified_stocks']} identified stocks.\n"
        f"Analyzed {m['scored_articles']} English texts; {m['event_clusters']} deduplicated stock-related stories; "
        f"read {m['publisher_pages_read']} publisher pages.\n"
        f"{m['sources_ok']}/{m['sources_attempted']} source queries succeeded.\n\n"
        "Ranking reflects catalyst evidence, novelty and changes in the observed sentiment sample. "
        "It is a research shortlist, not a probability of profit."
    ]
    previous = None
    for i, c in enumerate(report["candidates"], 1):
        group = "UNVERIFIED BUZZ / NEWS LEADS" if c["category"] == "Unverified buzz / news lead" else "OPPORTUNITY & RISK RESEARCH"
        prefix = f"{group}\n\n" if group != previous else ""
        previous = group
        lead = c["lead"]
        body = [f"{prefix}{i}. {c['ticker']} — {c['company']}",
                f"{c['category']} | priority {c['priority']}/100",
                f"Headline: {short_title(lead['title'])}",
                f"Evidence ({c['evidence_confidence']}): {lead['evidence']}.\n"
                f"Time: {lead['published_at']} ({lead['timestamp_basis']}).",
                f"Sentiment: {lead['tone']}; sample score {c['sample_sentiment']:+.2f} on −1 to +1. "
                f"{c['stories']} stories / {c['publishers']} publishers / {c['social_posts']} sampled social posts.",
                f"Opportunity hypothesis: {c['hypothesis']}", f"What could undermine it: {c['risk']}"]
        if c["attention_ratio"] is not None:
            body.append(f"Observed attention: {c['attention_ratio']:.1f}× the mean over {c['baseline']['days']} comparable prior runs.")
        if c["sentiment_shift"] is not None:
            body.append(f"Sample sentiment change: {c['sentiment_shift']:+.2f} against the comparable baseline.")
        if c["contrary"]:
            a = c["contrary"][0]
            body.append(f"Counterpoint to check: {short_title(a['title'])}\n{a['url']}")
        body.append("Source: " + lead["url"])
        sections.append("\n".join(body))
    if not report["candidates"]:
        sections.append("No candidates met the research threshold in the accessible sample. "
                        "A thin or unavailable feed is not evidence that the market had no news.")
    unavailable = sorted({x["source"].split(":")[0] for x in report["coverage"] if x["status"] != "ok"})
    sections.append("COVERAGE & METHOD\n"
                    f"Unavailable source families: {', '.join(unavailable) or 'None among attempted queries'}.\n"
                    f"Potentially capped query results: {m['capped_queries']}. "
                    f"Unscored due to language/cap: {m['unscored_articles']}.\n"
                    "Duplicate articles are clustered; publisher count is not independent corroboration. "
                    "Social metrics describe the collected sample only. Publication/discovery time may differ from event time.\n"
                    "Medium evidence confidence means a source page was read, with independent corroboration still open; "
                    "Low means excerpt/social evidence only. No automated claim receives a verified label. "
                    "Social author counts are unverified account labels; bot campaigns are not reliably detected.\n"
                    "A missing trend means insufficient comparable prior runs; no acceleration claim. "
                    "Trends use broad discovery only, excluding adaptive follow-up. "
                    "If no counterpoint appears, none was found in the sample; this is not proof none exists. "
                    "Valuation, price reaction and what is already priced in remain unverified.\n"
                    + "\n".join(report["coverage_notes"]) + "\n"
                    "Method: local financial-text classifier plus explicit catalyst rules. "
                    "Interpretations are hypotheses; social slang, sarcasm and multi-company stories can be misclassified.")
    return sections


def save(report: dict, path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    sections = render(report)
    (path / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    (path / "report.txt").write_text("\n\n".join(sections) + "\n")
    (path / "report.md").write_text("# Daily Stock News & Sentiment\n\n" + "\n\n---\n\n".join(sections) + "\n")
