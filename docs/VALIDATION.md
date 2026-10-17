# Validation record

**Deployment update (2026-10-17):** scheduling has moved into this repository's `.github/workflows/news.yml`. The external caller described below is historical and has been removed. See [operations](OPERATIONS.md) for the current setup, including the two Telegram secrets required here. The following records document the original 2026-10-16 validation, not a successful delivery after migration.

Validation date: 2026-10-16. Local validation sent no Telegram messages. The first hosted production run subsequently delivered the report, as recorded below.

## Offline checks

- 29 standard-library tests passed, including one end-to-end fixture through collection, ranking, provenance serialization and report rendering.
- Python compilation succeeded.
- Both GitHub workflow files and the caller template parsed as YAML.
- Git whitespace validation passed.
- The pinned financial-text model was downloaded and exercised with real local CPU inference.

## Broad live collection

A full no-send scan of the expanded source configuration produced the following measured results, before the final entity and ranking refinements:

| Metric | Observed |
| --- | ---: |
| Eligible listed securities in the directory | 5,951 |
| In-window records, including follow-up | 2,071 |
| Unique article URLs | 1,861 |
| Publisher labels/domains | 327 |
| Stock-related English texts scored | 1,013 |
| Successful discovery/follow-up queries | 99 / 123 |
| Publisher pages read / attempted | 28 / 100 |
| Potentially capped queries | 17 |

GDELT, Bluesky, five Reddit communities, CNBC and Yahoo had unavailable queries in this environment. Google News often returned an aggregator page rather than a readable original. Those pages retained excerpt-only status. Direct GlobeNewswire feeds supplied accessible issuer releases. These measurements are not a guarantee of tomorrow's coverage or hosted-runner access.

Manual review identified three false entity matches: Nasdaq as an exchange, Pearson as an airport name, and Universal in a registration-document title. Regression tests now require legal-name/explicit-symbol evidence for these ambiguous names. Single-word name matches also require company/stock context. The ranker now requires a headline catalyst rather than relying on company-description boilerplate, and excludes routine conference/hiring notices.

## Focused validation after entity corrections

A fresh direct-release scan returned 126 in-window records, 111 unique URLs, 21 resolved stocks and 22 scored English texts. All 12 configured release feeds succeeded, and all 12 attempted original-page reads succeeded. The corrected entity logic excluded the three observed false matches. A replay of those collected event records through the tightened ranker excluded the routine conference, hiring and community-opening examples.

These focused results validate the corrections, not full-source coverage. The stored sample is marked as a smoke/validation report and cannot be sent by the delivery command. Synthetic examples are also refused.

## Hosted deployment and first delivery

The public repository is live at [eladyesh/stock-news-sentiment-daily](https://github.com/eladyesh/stock-news-sentiment-daily). Application commit `2146cdd8eb2903aaad3ffcba625ecf5c854a11f3` passed the [hosted test workflow](https://github.com/eladyesh/stock-news-sentiment-daily/actions/runs/38942661794), including all 29 offline tests and the integration fixture.

The [scheduled caller](https://github.com/eladyesh/stock-screener-daily/actions/workflows/daily_news_sentiment.yml) is installed on the default branch of `stock-screener-daily` at commit `8f77a9f38c1cfbd395427164ca3c3d62838624c3`. Both the reusable workflow and application checkout are pinned to the tested application commit. It passes the existing encrypted `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` secrets to the reusable workflow; their values were not copied or retrieved. The existing screener workflow is unchanged.

The caller schedules collection at 07:30 in `Asia/Jerusalem`, then holds the completed report until 08:00. GitHub queue delays can make delivery late. The new repository's separate standalone schedule remains opt-in to avoid duplicate deliveries. An actual scheduled 08:00 invocation has not yet occurred; the first production verification used manual dispatch, which sends immediately.

The [first production run](https://github.com/eladyesh/stock-screener-daily/actions/runs/38942875956) completed successfully in 4 minutes 19 seconds. Its delivery step finished at 17:55:41 UTC on 2026-10-16 and logged **"Telegram confirmed 4 new report messages."** The application checked Telegram's message receipts against the configured private destination. The delivery journal and report artifacts were saved successfully.

| Metric | First hosted production run |
| --- | ---: |
| Eligible listed securities | 5,951 |
| In-window records, including follow-up | 1,868 |
| Unique article URLs | 1,726 |
| Publisher labels/domains | 355 |
| Identified stocks | 408 |
| Stock-related English texts scored | 689 |
| Successful discovery/follow-up queries | 89 / 123 |
| Publisher pages read / attempted | 50 / 100 |
| Potentially capped queries | 5 |
| Routine notices excluded | 77 |
| Final report candidates | 12 |
| Telegram messages with confirmed receipts | 4 |

These are observed results for one run, not complete web coverage. A publisher label in search results does not mean its original article was read. The report preserves this distinction and records unavailable sources separately.
