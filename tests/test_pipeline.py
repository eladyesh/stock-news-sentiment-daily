from __future__ import annotations

from datetime import datetime, timedelta
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from news_scout.analysis import comparable_baseline, deduplicate, headline_key, rank, story_groups
from news_scout.core import Article, UTC, canonical_url, iso, timestamp
from news_scout.http import public_url
from news_scout.report import render
from news_scout.sources import Collector, parse_bluesky, parse_feed, parse_gdelt
from news_scout.telegram import Telegram, deliver, split_messages, units
from news_scout.universe import Resolver, parse_directory

NOW = datetime(2026, 10, 16, 5, 0, tzinfo=UTC)
CONFIG = json.loads((Path(__file__).parents[1] / "config.json").read_text())


def article(title="Acme Robotics raises revenue guidance", url="https://example.com/a", **kwargs):
    data = dict(title=title, url=url, published_at=iso(NOW - timedelta(hours=1)),
                tickers=["ACME"], score=.8, tone="positive", publisher="example.com",
                read_status="publisher page read", evidence="company release read; issuer claim")
    data.update(kwargs)
    return Article(**data)


def report_for_delivery(**overrides):
    m = dict(raw_records=500, unique_articles=300, unique_publishers=40, identified_stocks=70,
             scored_articles=200, event_clusters=150, publisher_pages_read=20, sources_ok=40,
             sources_attempted=47, capped_queries=2, unscored_articles=10)
    result = dict(date="2026-10-16", generated_at=iso(NOW), window_start=iso(NOW-timedelta(hours=24)),
                  timezone="Asia/Jerusalem", smoke=False, metrics=m, candidates=[], coverage=[], coverage_notes=[])
    result.update(overrides)
    return result


class FakeBot:
    chat_id = "12345"
    def __init__(self, fail_at=None):
        self.calls, self.verified, self.fail_at = [], 0, fail_at
    def verify(self):
        self.verified += 1
    def call(self, method, data):
        self.calls.append(data)
        if self.fail_at == len(self.calls):
            raise RuntimeError("uncertain transport result")
        return {"message_id": len(self.calls), "chat": {"id": int(self.chat_id), "type": "private"}}


class SourceTests(unittest.TestCase):
    def test_dates_require_timezone(self):
        self.assertIsNone(timestamp("2026-10-16T08:00:00"))
        self.assertEqual(timestamp("2026-10-16T08:00:00+03:00"), NOW)
        self.assertEqual(timestamp("20261016T050000Z"), NOW)

    def test_rss_missing_dates_not_made_current(self):
        data = b'''<rss><channel><item><title>Old or undated</title><link>https://example.com/a</link></item>
        <item><title>Acme news</title><link>https://example.com/b</link><pubDate>Fri, 16 Oct 2026 04:00:00 GMT</pubDate></item></channel></rss>'''
        rows = parse_feed(data, "fixture", "news")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].evidence, "unverified lead")

    def test_social_atom_keeps_author_and_unverified_claim(self):
        data = b'''<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>$ACME rumor</title>
        <link href="https://example.com/post"/><updated>2026-10-16T04:00:00Z</updated>
        <author><name>test-author</name></author><content>Unverified claim</content></entry></feed>'''
        row = parse_feed(data, "reddit:test", "social")[0]
        self.assertEqual(row.author, "test-author")
        self.assertEqual(row.evidence, "unverified social claim")
        self.assertNotIn("author", row.metadata())

    def test_gdelt_does_not_invent_publication_time(self):
        row = parse_gdelt({"articles":[{"title":"Acme", "url":"https://example.com", "seendate":"20261016T040000Z"}]}, "gdelt")[0]
        self.assertIn("first seen", row.timestamp_basis)
        self.assertIsNone(row.event_at)

    def test_future_and_old_items_are_excluded(self):
        class Client:
            def get(self, url):
                return (b'''<rss><channel>
                <item><title>Future</title><link>https://example.com/a</link><pubDate>Fri, 16 Oct 2026 06:00:00 GMT</pubDate></item>
                <item><title>Old</title><link>https://example.com/b</link><pubDate>Wed, 14 Oct 2026 06:00:00 GMT</pubDate></item>
                </channel></rss>''', url, "application/xml")
        c = Collector(Client(), CONFIG, NOW)
        result = c.execute([{"kind":"rss", "family":"news", "name":"test", "url":"https://example.com"}], stage="discovery")
        self.assertEqual(result, [])
        self.assertEqual(c.coverage[0]["returned"], 2)
        self.assertEqual(c.coverage[0]["in_window"], 0)

    def test_source_failure_is_not_zero_news_success(self):
        class Client:
            def get(self, url):
                raise TimeoutError("do not log request secrets")
        c = Collector(Client(), CONFIG, NOW)
        self.assertEqual(c.execute([{"kind":"rss", "family":"news", "name":"test", "url":"https://example.com"}], stage="discovery"), [])
        self.assertEqual(c.coverage[0]["status"], "unavailable")
        self.assertNotIn("secrets", c.coverage[0]["reason"])

    def test_bluesky_uses_did_and_separates_claim_from_post(self):
        row = parse_bluesky({"posts":[{"uri":"at://did:plc:abc/app.bsky.feed.post/123", "record":{"text":"$ACME rumor", "createdAt":"2026-10-16T04:00:00Z", "langs":["en"]}, "author":{"did":"did:plc:abc"}}]}, "bsky")[0]
        self.assertIn("did:plc:abc", row.url)
        self.assertEqual(row.evidence, "unverified social claim")


class EntityAndEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.resolver = Resolver({"ACME":"Acme Robotics Inc. - Common Stock", "BE":"Bloom Energy Corporation", "ON":"ON Semiconductor Corporation"})

    def test_common_words_do_not_become_tickers(self):
        self.assertEqual(self.resolver.resolve("BE ON IT: CEO discusses EPS and AI"), [])
        self.assertEqual(self.resolver.resolve("Bloom Energy announces results"), ["BE"])
        self.assertEqual(self.resolver.resolve("$BE and NASDAQ: ON"), ["BE", "ON"])

    def test_etfs_warrants_test_issues_excluded_adrs_retained(self):
        data = "Symbol|Security Name|Test Issue|ETF\nA|Acme Common Stock|N|N\nETF|Index Fund|N|Y\nWT|Acme Warrants|N|N\nTEST|Fake|Y|N\nADR|Issuer American Depositary Shares|N|N\n"
        self.assertEqual(set(parse_directory(data)), {"A", "ADR"})

    def test_exchange_airport_and_document_words_are_not_issuer_matches(self):
        resolver = Resolver({"NDAQ":"Nasdaq, Inc. - Common Stock", "PSO":"Pearson plc",
                             "UVV":"Universal Corporation", "MDXH":"MDxHealth SA",
                             "NVDA":"NVIDIA Corporation"})
        for text in ["MDxHealth announces revenue guidance (Nasdaq: MDXH)",
                     "Toronto Pearson strengthens an airport partnership",
                     "Bonduelle Universal Registration Document"]:
            self.assertFalse(set(resolver.resolve(text)) & {"NDAQ", "PSO", "UVV"})
        self.assertEqual(resolver.resolve("Nasdaq, Inc. announces earnings"), ["NDAQ"])
        self.assertEqual(resolver.resolve("Universal Corporation reports revenue"), ["UVV"])
        self.assertEqual(resolver.resolve("NVIDIA raises guidance"), ["NVDA"])
        self.assertEqual(resolver.resolve("NVIDIA (NVDA) shares advance"), ["NVDA"])
        self.assertEqual(resolver.resolve("$PSO and NYSE: UVV"), ["PSO", "UVV"])

    def test_tracking_params_do_not_multiply_articles(self):
        rows = [article(url="https://example.com/a?utm_source=x"), article(url="https://example.com/a?utm_source=y")]
        self.assertEqual(len(deduplicate(rows)), 1)
        self.assertIn("id=2", canonical_url("https://example.com/a?id=2&utm_source=x"))

    def test_syndication_one_story_but_opposite_claim_separate(self):
        rows = [article(url=f"https://p{i}.example/a") for i in range(5)]
        self.assertEqual(len(story_groups(rows)), 1)
        rows.append(article("Acme Robotics cuts revenue guidance", url="https://p6.example/a", score=-.8))
        self.assertEqual(len(story_groups(rows)), 2)

    def test_changed_numbers_are_not_lost(self):
        rows = [article("Acme revenue forecast 10 million"), article("Acme revenue forecast 20 million", url="https://example.com/b")]
        self.assertEqual(len(story_groups(rows)), 2)

    def test_no_body_read_cannot_be_presented_as_supported(self):
        row = article(read_status="feed excerpt only", evidence="unverified lead")
        selected, _, _ = rank([row], self.resolver, {}, "sig", "2026-10-16", CONFIG)
        self.assertEqual(selected[0]["category"], "Unverified buzz / news lead")

    def test_company_boilerplate_does_not_create_a_material_catalyst(self):
        rows = [article("Acme Robotics opens its new visitor center", text="Acme has substantial revenue and defense contracts."),
                article("Acme Robotics to host a skilled trades hiring event", url="https://example.com/jobs", text="The company maintains a large backlog.")]
        selected, _, _ = rank(rows, self.resolver, {}, "sig", "2026-10-16", CONFIG)
        self.assertEqual(selected, [])

    def test_prior_story_without_change_not_repeated(self):
        row = article()
        selected, _, _ = rank([row], self.resolver, {"seen_headlines":{headline_key(row):iso(NOW-timedelta(days=1))}}, "sig", "2026-10-16", CONFIG)
        self.assertEqual(selected, [])

    def test_calendar_and_lawfirm_ads_do_not_displace_material_events(self):
        for title in ["Acme Robotics to report quarterly results on November 5",
                      "Acme Robotics announces earnings conference call date",
                      "Acme Robotics to highlight its new research at the annual meeting",
                      "Acme Robotics shareholder deadline reminder from law firm"]:
            selected, _, _ = rank([article(title)], self.resolver, {}, "sig", "2026-10-16", CONFIG)
            self.assertEqual(selected, [], title)
        selected, _, _ = rank([article("Acme Robotics reports quarterly results and raises guidance")], self.resolver, {}, "sig", "2026-10-16", CONFIG)
        self.assertEqual(len(selected), 1)

    def test_zero_and_mismatched_baselines_do_not_create_infinite_acceleration(self):
        state = {"daily":[{"date":f"2026-10-{d}", "signature":"sig", "stocks":{}} for d in [13,14,15]]}
        self.assertIsNone(comparable_baseline(state, "ACME", "other", "2026-10-16"))
        selected, _, _ = rank([article()], self.resolver, state, "sig", "2026-10-16", CONFIG)
        self.assertIsNone(selected[0]["attention_ratio"])
        self.assertIsNone(selected[0]["sentiment_shift"])

    def test_same_day_not_used_as_prior_baseline(self):
        state = {"daily":[{"date":"2026-10-16", "signature":"sig", "stocks":{"ACME":{"count":99,"score":1}}}]}
        self.assertIsNone(comparable_baseline(state,"ACME","sig","2026-10-16"))

    def test_repeated_syndication_does_not_raise_sentiment_sample_size(self):
        rows = [article(url=f"https://p{i}.example/a") for i in range(12)]
        selected, snap, _ = rank(rows, self.resolver, {}, "sig", "2026-10-16", CONFIG)
        self.assertEqual(snap["ACME"]["count"], 1)
        self.assertEqual(selected[0]["stories"], 1)

    def test_adaptive_followup_does_not_inflate_attention_baseline(self):
        rows = [article(), article("Acme Robotics wins a new contract", url="https://example.com/new", collector="followup:ACME:original")]
        _, snap, _ = rank(rows, self.resolver, {}, "sig", "2026-10-16", CONFIG)
        self.assertEqual(snap["ACME"]["count"], 1)

    def test_private_urls_refused_before_network(self):
        for url in ["file:///etc/passwd", "http://127.0.0.1/x", "https://localhost/x", "https://169.254.169.254/latest", "https://user:pass@example.com"]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                public_url(url)


class TelegramConfigurationTests(unittest.TestCase):
    def test_bot_own_id_is_rejected_without_sending(self):
        bot = Telegram("999:fixture-token", "999")
        with patch.object(bot, "call", return_value={"id":999, "is_bot":True}) as call:
            with self.assertRaisesRegex(ValueError, "getMe returns the bot's ID"):
                bot.verify()
        call.assert_called_once_with("getMe", {})

    def test_private_recipient_is_verified_without_sending(self):
        bot = Telegram("999:fixture-token", "12345")
        with patch.object(bot, "call", side_effect=[{"id":999, "is_bot":True}, {"id":12345, "type":"private"}]) as call:
            bot.verify()
        self.assertEqual([x.args[0] for x in call.call_args_list], ["getMe", "getChat"])

    def test_rejection_guidance_never_echoes_error_body_or_credentials(self):
        bot = Telegram("999:fixture-token", "12345")
        for body, expected in [
            (json.dumps({"ok":False, "description":"Forbidden: bot was blocked by the user"}).encode(), "Unblock the bot"),
            (json.dumps({"ok":False, "description":f"secret {bot.token} {bot.chat_id}"}).encode(), "credentials omitted"),
            (b"not json", "credentials omitted"),
            (json.dumps({"description":[]}).encode(), "credentials omitted"),
        ]:
            error = HTTPError("redacted", 403, "Forbidden", {}, BytesIO(body))
            with self.subTest(body=body), patch("news_scout.telegram.build_opener") as opener:
                opener.return_value.open.side_effect = error
                with self.assertRaisesRegex(RuntimeError, expected) as raised:
                    bot.call("sendMessage", {"chat_id":bot.chat_id, "text":"fixture"})
                self.assertNotIn(bot.token, str(raised.exception))
                self.assertNotIn(bot.chat_id, str(raised.exception))


class DeliveryTests(unittest.TestCase):
    def test_utf16_limits_and_no_dropped_text(self):
        sections = ["A"*8000, "😀"*4000, "Final line"]
        messages = split_messages(sections)
        self.assertTrue(all(units(x) <= 4096 for x in messages))
        joined = "".join(x.split("\n",1)[1] for x in messages)
        self.assertEqual(joined.count("A"),8000)
        self.assertEqual(joined.count("😀"),4000)
        self.assertIn("Final line",joined)

    @patch("news_scout.telegram.time.sleep")
    def test_successful_rerun_does_not_send_again(self, _):
        with tempfile.TemporaryDirectory() as d:
            p, bot = Path(d)/"state.json", FakeBot()
            report = report_for_delivery()
            n = deliver(report,p,bot,NOW)
            self.assertGreater(n,0)
            self.assertEqual(deliver(report,p,bot,NOW),0)
            self.assertEqual(len(bot.calls),n)

    @patch("news_scout.telegram.time.sleep")
    def test_ambiguous_send_is_not_blindly_retried(self, _):
        with tempfile.TemporaryDirectory() as d:
            p, bot = Path(d)/"state.json", FakeBot(fail_at=1)
            with self.assertRaises(RuntimeError): deliver(report_for_delivery(),p,bot,NOW)
            self.assertTrue(json.loads(p.read_text())["delivery"]["2026-10-16"]["uncertain"])
            with self.assertRaises(RuntimeError): deliver(report_for_delivery(),p,bot,NOW)
            self.assertEqual(len(bot.calls),1)

    def test_wrong_day_future_old_and_smoke_reports_refused(self):
        with tempfile.TemporaryDirectory() as d:
            for override in [{"date":"2026-10-15"}, {"generated_at":iso(NOW+timedelta(minutes=1))},
                             {"generated_at":iso(NOW-timedelta(hours=7))}, {"smoke":True}, {"synthetic":True}]:
                with self.subTest(override=override), self.assertRaises(ValueError):
                    deliver(report_for_delivery(**override),Path(d)/"state.json",FakeBot(),NOW)

    @patch("news_scout.telegram.time.sleep")
    def test_wrong_destination_receipt_leaves_uncertain_journal(self, _):
        class WrongBot(FakeBot):
            def call(self, method, data):
                return {"message_id":1, "chat":{"id":99999,"type":"private"}}
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/"state.json"
            with self.assertRaises(RuntimeError):
                deliver(report_for_delivery(),p,WrongBot(),NOW)
            self.assertTrue(json.loads(p.read_text())["delivery"]["2026-10-16"]["uncertain"])

    def test_report_never_claims_baseline_on_first_run(self):
        row = article()
        selected,_,_ = rank([row],Resolver({"ACME":"Acme Robotics"}),{},"sig","2026-10-16",CONFIG)
        text = "\n".join(render(report_for_delivery(candidates=selected)))
        self.assertIn("insufficient comparable prior runs",text)
        self.assertIn("Opportunity hypothesis:",text)
        self.assertIn("What could undermine it:",text)


class PipelineIntegrationTests(unittest.TestCase):
    def test_research_output_is_serializable_and_keeps_provenance_without_article_bodies(self):
        from news_scout.__main__ import run

        class FixtureCollector:
            def __init__(self, client, config, now):
                self.coverage = [{"source":"fixture", "status":"ok", "in_window":1}]
                self.page_reads = []
            def discover(self, smoke=False):
                return [article(text="Private in-memory article excerpt", read_status="feed excerpt only", evidence="unverified lead")]
            def follow_up(self, candidates, smoke=False):
                return []
            def read_pages(self, rows):
                for row in rows:
                    row.read_status = "publisher page read"
                    row.evidence = "company release read; issuer claim"
                    self.page_reads.append({"url":row.url,"status":row.read_status})

        class FixtureModel:
            def apply(self, rows):
                for row in rows:
                    row.score, row.tone, row.probability = .8, "positive", .9

        with patch("news_scout.__main__.fetch_universe", return_value={"ACME":"Acme Robotics Inc."}), \
             patch("news_scout.__main__.Collector", FixtureCollector):
            report, state = run(CONFIG, {}, client=object(), model=FixtureModel(), now=NOW)
        self.assertEqual(report["candidates"][0]["evidence_confidence"], "Medium")
        self.assertEqual(report["metrics"]["publisher_pages_read"], 1)
        self.assertEqual(report["event_ledger"][0]["independent_corroboration"], "not established")
        self.assertNotIn("Private in-memory article excerpt", json.dumps(report))
        self.assertEqual(state["daily"][0]["stocks"]["ACME"]["count"], 1)
        self.assertIn("Acme Robotics", "\n".join(render(report)))


if __name__ == "__main__":
    unittest.main()
