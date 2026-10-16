# Daily Stock News & Sentiment Opportunities

A free daily research pipeline that searches broadly for **US-listed stock opportunities**, investigates promising news, and sends a compact **English Telegram report**. Based on the [news-sentiment skill](https://github.com/eladyesh/stock-market-skills/tree/main/skills/news-sentiment).

The collection universe is broad. The **15-candidate limit applies only to the final report**, including at most three unverified buzz leads. Quiet or poorly sourced days produce fewer candidates rather than filler.

**Deployment:** the [daily Telegram workflow](https://github.com/eladyesh/stock-screener-daily/actions/workflows/daily_news_sentiment.yml) is installed in `stock-screener-daily`, using this repository's application and the existing Telegram secrets. It targets 08:00 Israel time, starting research at 07:30. The deployed application is pinned to commit `2146cdd8eb2903aaad3ffcba625ecf5c854a11f3`.

## What it does

1. Refreshes the Nasdaq and other-US-exchange listing directories. Common stocks and ADRs are eligible; ETFs, test issues, preferred shares, warrants, units and similar instruments are excluded. This is exchange-listed discovery, not OTC coverage.
2. Searches 24 broad Google News queries, 12 GDELT queries, seven Reddit communities, four Bluesky queries, and 16 direct news/release feeds. Aggregator results can span hundreds of publishers; these are bounded samples, not an exhaustive internet crawl.
3. Resolves company names and explicit cashtags/exchange symbols. It does not mistake ordinary words such as `BE` or `ON` for stocks. Single-word aliases require company/stock context; ambiguous names such as Nasdaq, Pearson and Universal require a legal name or explicit ticker.
4. Deduplicates URLs and similar stories, suppresses routine earnings-calendar notices and shareholder-solicitation ads, and scores up to 10,000 English financial texts locally.
5. Searches for original and contrary evidence on up to 30 leading stocks. Reads up to 100 publisher pages, reserving half the budget for directly accessible articles.
6. Ranks new catalysts, adverse developments, sentiment changes and news/social disagreement. Separates sourced research from **unverified buzz / news leads**.
7. Sends the report to the existing verified private Telegram destination. Saves a coverage ledger, event/source metadata and the report as seven-day Actions artifacts.

The local classifier scores financial language. Business explanations use transparent catalyst rules and explicitly labeled hypotheses; this is not a general-purpose LLM analyst or a validated trading signal. No buy orders are placed.

## Daily delivery

The intended delivery time is **08:00 Asia/Jerusalem**, including daylight-saving changes. The scheduled workflow starts at **07:30**, collects the preceding 24 hours as of scan start, then holds a completed report until 08:00. If GitHub starts late or research overruns, delivery is late. GitHub Actions does not guarantee exact-time execution.

The default deployment uses the existing `eladyesh/stock-screener-daily` repository as the scheduled caller:

- This repository owns the application and reusable workflow: `.github/workflows/news.yml`.
- The existing repository owns the tiny caller: `.github/workflows/daily_news_sentiment.yml`.
- The caller explicitly passes its existing `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` secrets. Their values never need to be extracted or copied.
- The existing stock-screening workflow continues independently.
- Only one scheduler should be active. This repository's own scheduled job stays disabled unless `NEWS_STANDALONE_ENABLED=true` is set as a repository variable.

After creating this public repository, add [the caller template](examples/telegram-caller.yml) to the existing repository. Pin both its `uses` reference and `code_ref` to the reviewed commit SHA. Updates then require changing both pins.

For a standalone deployment instead, set the same two secrets in this repository, enable `NEWS_STANDALONE_ENABLED=true`, and disable the external caller. Never enable both routes for the same destination: their histories and delivery journals are separate.

GitHub can disable scheduled workflows in inactive public repositories after 60 days. Check the Actions page periodically and re-enable the schedule if GitHub disables it.

## Run locally

Python 3.12 is used in Actions. The app uses standard-library collectors, a pinned CPU-only PyTorch installation, `transformers`, and `langdetect`.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install torch==2.9.1 --index-url https://download.pytorch.org/whl/cpu
python -m pip install -r requirements.txt
python -m news_scout run --smoke
python -m news_scout run
```

Both commands generate `output/report.txt`, `output/report.md`, and `output/report.json`. They **do not send anything or persist observation history**. The smoke check intentionally samples a small source subset; it cannot be sent through the delivery command.

The first full run downloads the pinned financial-text model. It runs locally on CPU and requires no inference API key. Subsequent local runs reuse the Hugging Face download cache.

For explicit delivery, provide the two environment variables through a secure local environment or GitHub Secrets; `.env.example` documents their names. The app does not automatically load a `.env` file.

```bash
python -m news_scout verify-telegram
python -m news_scout run --prepare-delivery
python -m news_scout send
```

`verify-telegram` checks the configured private chat without sending a message. `--prepare-delivery` persists the day's report and seven-day history. A repeat preparation on the same day reuses that exact report.

```bash
python -m unittest discover -s tests -v
```

The offline tests require no model download, credentials or network access. They cover evidence classification, ticker ambiguity, deduplication, changed numbers/claims, misleading notices, missing coverage, baseline comparability, message size and delivery receipts/retries.

## Report interpretation

Each candidate contains its ticker, headline, source/date, observed sentiment, research priority, business hypothesis and a risk that could undermine it. Counterpoints are included when found. Model sentiment and factual reliability are separate.

- **Medium evidence confidence:** a matching original/publisher page was read. An issuer release remains an issuer claim. Independent corroboration and the meaning of the claim still require review.
- **Low evidence confidence:** only a feed excerpt, inaccessible article or social claim is available. These candidates appear separately and are capped at three.
- **Verified:** never assigned automatically. Reading a page does not establish that every statement is true.

The score is `P(positive) - P(negative)`, between -1 and +1; neutral probability reduces its magnitude. Story clusters receive one vote. This is not a population-level sentiment percentage or a probability of profit. The model may misread sarcasm, promotional language, negation and multi-company articles.

Priority combines headline catalyst relevance (5–30 points), source-page evidence (0/12/20), novelty (up to 10), comparable attention change (up to 15), sentiment change (up to 15), and news/social divergence (10). The threshold is 35; the score is capped at 100. Generic company-description text does not establish a catalyst. Attention-only stories need a measured trend change, and routine hiring/event notices are suppressed. These are research heuristics, not backtested return predictions.

Attention and sentiment trends require at least three prior completed runs with the same configuration and healthy discovery-query set. They use **broad discovery only**, excluding adaptive follow-up searches. Missing or zero-count baselines do not generate fabricated acceleration. Cache loss starts a new baseline.

Current valuation, dated consensus, price reaction and whether news is already priced in are **not established** by this version. A headline reporting growth is not treated as proof of a consensus beat or an undervalued stock. Event time remains unknown unless supported; publication and GDELT discovery times are not silently substituted for it.

## Coverage and customization

Edit [config.json](config.json) to add independent public feeds, sectors, catalyst searches or communities. No ticker watchlist restricts discovery. A configurable work cap protects runtime, and actual collected/analyzed counts appear in every report.

Every attempted discovery/follow-up query records its URL, status, returned/in-window counts and possible truncation. Every publisher-read attempt has an outcome. The JSON report includes an event ledger with URLs, publisher labels, timing basis, retrieval time and evidence class. Article bodies and social author identifiers are not archived; aggregate author counts are account labels, not verified people.

Blocked endpoints remain **unavailable**, never “zero discussion.” There is no paywall bypass, proxy rotation or challenge solving. X, Stocktwits, private groups and chat channels are not directly covered in this free configuration; articles discussing them are secondary leads. Reddit and Bluesky cover only accessible samples. Aggregators can omit important small-cap news, and a source can return a successful but empty feed.

See [source documentation](docs/SOURCES.md), [operations](docs/OPERATIONS.md), and the [synthetic sample report](examples/sample-report.md).

## Cost and credentials

No paid news service, paid AI API, GitHub Models service, or paid runner is used. Workflows refuse execution for private caller repositories and use standard public-repository runners. Artifacts expire after seven days; history caches are small and disposable. Keep the repository public for this free deployment.

Telegram credentials exist only in the verification and delivery steps. Collection and model inference receive neither secret. Logs omit bot tokens, chat IDs and API response bodies. The bot only sends to the configured, verified private chat.

## Delivery reliability

Messages are split within Telegram's UTF-16 length limit, with previews disabled. A per-day journal records confirmed message receipts and resumes from the next unsent message. A network timeout leaves an uncertain marker and stops automatic retries so the next run does not blindly send the same message again.

The journal is stored in an Actions cache. Cache eviction or a runner crash before the updated cache is saved can still cause duplicates. This is **best-effort deduplication, not an exactly-once guarantee**. Reports older than six hours, future-dated reports, wrong-day reports, smoke reports and synthetic examples are refused by the sender. See operations for recovery.
