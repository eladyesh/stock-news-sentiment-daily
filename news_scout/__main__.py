from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import json
import os
import time
from pathlib import Path
from zoneinfo import ZoneInfo

from .analysis import FinancialSentiment, catalyst, deduplicate, headline_key, rank, routine_notice, story_groups
from .core import UTC, digest, iso, timestamp
from .http import Client
from .report import save
from .sources import Collector
from .telegram import Telegram, atomic_json, deliver
from .universe import Resolver, fetch_universe


def run(config, state, *, smoke=False, client=None, model=None, now=None):
    now = now or datetime.now(UTC)
    client = client or Client()
    resolver = Resolver(fetch_universe(client))
    collector = Collector(client, config, now)
    print(f"Universe: {len(resolver.names)} eligible listed securities. Starting broad discovery.", flush=True)
    initial = collector.discover(smoke=smoke)
    if not any(c["status"] == "ok" and c["in_window"] for c in collector.coverage):
        raise RuntimeError("No current source records; refusing to produce a normal no-news report")
    unique = deduplicate(initial)
    for a in unique:
        a.tickers = resolver.resolve(a.title + " " + a.text[:1200])
    relevant = [a for a in unique if a.tickers and not routine_notice(a)]
    if not relevant:
        raise RuntimeError("No stock entities resolved; inspect source/universe compatibility")
    relevant.sort(key=lambda a: a.published_at, reverse=True)
    cap = min(config["max_scored_articles"], 120 if smoke else config["max_scored_articles"])
    model = model or FinancialSentiment(config)
    print(f"Collected {len(initial)} records; scoring {min(len(relevant), cap)} stock-related texts.", flush=True)
    model.apply(relevant[:cap])
    signature = digest(json.dumps({"config": config, "healthy": sorted(
        c["source"] for c in collector.coverage if c["status"] == "ok")}, sort_keys=True))
    date = now.astimezone(ZoneInfo(config["timezone"])).date().isoformat()
    _, _, preliminary = rank(relevant, resolver, state, signature, date, config)
    followup = collector.follow_up([(c["ticker"], c["company"]) for c in preliminary], smoke=smoke)
    print(f"Follow-up collected {len(followup)} records. Investigating publisher pages.", flush=True)
    combined = deduplicate(unique + followup)
    existing = {a.key: a for a in relevant if a.score is not None}
    for a in combined:
        a.tickers = resolver.resolve(a.title + " " + a.text[:1200])
        prior = existing.get(a.key)
        if prior:
            a.score, a.tone, a.probability = prior.score, prior.tone, prior.probability
    relevant = [a for a in combined if a.tickers and not routine_notice(a)]
    remaining = max(0, cap - len(existing))
    new = [a for a in relevant if a.score is None]
    model.apply(new[:remaining])
    # Read publishers for a diversified finalist set, not only the most-mentioned megacap.
    _, _, before_read = rank(relevant, resolver, state, signature, date, config)
    finalists = [c["ticker"] for c in before_read[:config["followup_stocks"]]]
    # Reserve half the budget for direct publisher URLs across the full universe.
    # Otherwise opaque aggregator links can consume every finalist-read attempt.
    direct = sorted((a for a in relevant if a.score is not None and a.family == "news"
                     and "news.google.com" not in a.url),
                    key=lambda a: (catalyst(a)[1], a.published_at), reverse=True)
    to_read = direct[:config["page_read_limit"] // 2]
    used = {a.key for a in to_read}
    for round_index in range(4):
        for ticker in finalists:
            pool = sorted((a for a in relevant if ticker in a.tickers and a.family == "news" and a.score is not None),
                          key=lambda a: ("news.google.com" not in a.url, catalyst(a)[1], a.published_at), reverse=True)
            if len(pool) > round_index:
                a = pool[round_index]
                if a.key not in used:
                    to_read.append(a)
                    used.add(a.key)
    collector.read_pages(to_read[:8] if smoke else to_read)
    selected, snapshot, _ = rank(relevant, resolver, state, signature, date, config)
    coverage = collector.coverage
    scored = [a for a in relevant if a.score is not None]
    metrics = {
        "universe_securities": len(resolver.names), "raw_records": len(initial) + len(followup),
        "unique_articles": len(combined), "duplicate_urls_removed": len(initial) + len(followup) - len(combined),
        "unique_publishers": len({a.publisher for a in combined if a.publisher}),
        "identified_stocks": len({t for a in relevant for t in a.tickers}),
        "scored_articles": len(scored), "unscored_articles": len(relevant) - len(scored),
        "event_clusters": len(story_groups(scored)),
        "publisher_pages_read": sum(a.read_status == "publisher page read" for a in relevant),
        "publisher_pages_attempted": len(collector.page_reads),
        "routine_notices_excluded": sum(routine_notice(a) for a in combined),
        "sources_ok": sum(x["status"] == "ok" for x in coverage), "sources_attempted": len(coverage),
        "capped_queries": sum(x.get("possibly_capped", False) for x in coverage),
        "followup_stocks": min(len(preliminary), 2 if smoke else config["followup_stocks"]),
    }
    report = {"date": date, "timezone": config["timezone"], "generated_at": iso(now),
              "window_start": iso(now - timedelta(hours=config["window_hours"])), "smoke": smoke,
              "metrics": metrics, "candidates": selected, "coverage": coverage, "page_reads": collector.page_reads,
              "coverage_notes": config["coverage_notes"], "model": config["model"],
              "model_revision": config["model_revision"], "signature": signature}
    report["event_ledger"] = [{"event_id": digest("|".join(sorted(a.key for a in group))),
                               "sources": [a.metadata() for a in group],
                               "independent_corroboration": "not established"}
                              for group in story_groups(scored)]
    cutoff = now - timedelta(days=config["context_days"])
    state["daily"] = [x for x in state.get("daily", []) if x["date"] != date and x["date"] >= cutoff.date().isoformat()]
    state["daily"].append({"date": date, "signature": signature, "stocks": snapshot, "smoke": smoke})
    state["seen_headlines"] = {k: v for k, v in state.get("seen_headlines", {}).items() if timestamp(v) and timestamp(v) >= cutoff}
    state["seen_headlines"].update({headline_key(a): iso(now) for a in scored})
    state["delivery"] = {k: v for k, v in state.get("delivery", {}).items() if k >= cutoff.date().isoformat()}
    return report, state


def main():
    parser = argparse.ArgumentParser(description="Free, broad-source stock news opportunity discovery")
    parser.add_argument("command", choices=["run", "send", "verify-telegram", "wait-for-delivery"])
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--output", default="output")
    parser.add_argument("--state", default="state/state.json")
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--prepare-delivery", action="store_true")
    args = parser.parse_args()
    if args.command == "wait-for-delivery":
        config = json.loads(Path(args.config).read_text())
        now = datetime.now(ZoneInfo(config["timezone"]))
        hour, minute = map(int, config["delivery_time"].split(":"))
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        delay = max(0, (target - now).total_seconds())
        if delay > 3600:
            raise ValueError("Scheduled delivery is more than one hour away; inspect the schedule")
        print(f"Waiting up to {round(delay)} seconds for {config['delivery_time']} {config['timezone']}.", flush=True)
        while (remaining := (target - datetime.now(target.tzinfo)).total_seconds()) > 0:
            time.sleep(min(30, remaining))
        return
    state_path, output = Path(args.state), Path(args.output)
    if args.command in {"send", "verify-telegram"}:
        bot = Telegram(os.getenv("TELEGRAM_BOT_TOKEN", ""), os.getenv("TELEGRAM_CHAT_ID", ""))
        if args.command == "verify-telegram":
            bot.verify()
            print("Configured private Telegram destination verified; no message sent.")
        else:
            report = json.loads((output / "report.json").read_text())
            print(f"Telegram confirmed {deliver(report, state_path, bot)} new report messages.")
        return
    config = json.loads(Path(args.config).read_text())
    if config.get("language") != "en" or not 1 <= config["max_report_stocks"] <= 15:
        raise ValueError("This project requires English and at most 15 report candidates")
    if args.smoke and args.prepare_delivery:
        raise ValueError("A smoke check cannot prepare scheduled delivery")
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    pending = state_path.parent / "pending_report.json"
    today = datetime.now(ZoneInfo(config["timezone"])).date().isoformat()
    if args.prepare_delivery and pending.exists():
        report = json.loads(pending.read_text())
        if report["date"] == today:
            save(report, output)
            print("Reusing this day's report and delivery journal; no duplicate research run.")
            return
    report, next_state = run(config, state, smoke=args.smoke)
    save(report, output)
    if args.prepare_delivery:
        atomic_json(state_path, next_state)
        atomic_json(pending, report)
    print(json.dumps(report["metrics"], sort_keys=True))
    print(f"Report ready: {len(report['candidates'])} candidates. Delivery is a separate command.")


if __name__ == "__main__":
    main()
