# Operations

## Deploy in this repository

1. Keep `eladyesh/stock-news-sentiment-daily` public and push this project to its default branch, `main`.
2. In **this repository's Settings → Secrets and variables → Actions**, add `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` with the existing bot and private-chat values. GitHub cannot reveal the values stored in another repository. Enter them directly in GitHub; never put credentials in code, logs, issues, or documentation.
3. Wait for the offline Tests workflow to pass. Manually dispatch **Daily News Sentiment Opportunities** with `smoke=true` and `send_telegram=false` to check hosted-runner access without sending.
4. For a full no-send check, set both inputs to `false`. For immediate delivery, set `smoke=false` and `send_telegram=true`. The workflow verifies the configured private destination before downloading the model or collecting news.
5. The native cron starts daily at 07:30 in `Asia/Jerusalem` and holds a completed scheduled report until 08:00. No `NEWS_STANDALONE_ENABLED` variable is needed. Check the delivery step, private chat and report coverage ledger; workflow success alone does not mean every source was accessible.

The former `.github/workflows/daily_news_sentiment.yml` caller in `stock-screener-daily` is removed. News runs no longer depend on that repository. Leave its Telegram secrets in place for its separate stock-screening workflow.

The old caller's history and delivery journal are not transferred. The first local run starts a fresh baseline, so do not manually resend on a day already delivered by the old caller.

## Daily state

`state/state.json` contains seven days of comparable aggregate observations, seen-headline hashes and the delivery cursor. `state/pending_report.json` is the exact day's report. Both are ignored by git and restored from/saved to an Actions cache scoped to `stock-news-sentiment-daily`.

The cache key changes for each run and attempt, restoring the most recent prefix match. Concurrent news runs are serialized. Cache misses deliberately reset history; the report must not claim acceleration until a comparable baseline exists again.

The sender requires the report's local date to match today and its generation time to be no more than six hours old. Research preparation is reused on same-day retries. A manual delivery counts as that day's report, so a later scheduled retry does not intentionally send a second edition.

## Investigate failures

| Symptom | Where to look | Recovery |
| --- | --- | --- |
| Missing Telegram secret | Verification-step error before model installation | Add both secrets in `stock-news-sentiment-daily`; secrets in the former caller are not inherited |
| Private destination not verified | Verification-step error | Check the existing bot/chat configuration and that the bot is started |
| No current source records / no entities resolved | Research-step error and source availability | Inspect upstream feeds/listing directories; rerun after fixing access |
| Some source families unavailable | `report.json` coverage entries | Keep the gap visible; add a legitimate accessible public alternative |
| Model download failure | Installation/research logs | Retry the download; do not silently substitute a different model |
| Uncertain Telegram send | Delivery journal and actual chat | Review the last message before clearing uncertainty; do not blindly rerun |
| Late report | Workflow start/step timestamps | Compare scheduled 07:30, scan duration and target 08:00; GitHub is best effort |
| No daily workflow | Actions schedule status | Check default branch and public-repository inactivity disabling |

If a Telegram call times out after the request was sent, the server may already have accepted it. Confirm the numbered message in the chat against the cursor. For manual local recovery, download the relevant Actions cache using authenticated GitHub tooling, inspect the state locally, and change the cursor only after confirming delivery. Keep the same pending report/fingerprint. Do not publish the cache. The app intentionally has no automatic “clear uncertainty and resend” button.

If the cache was evicted or lost before save, local receipts cannot guarantee deduplication. Check the chat before manually sending again. A report that is now stale should be skipped; the next day's run creates a new dated report.

## Workflow controls

- **Manual smoke:** `smoke=true`, `send_telegram=false`; limited access check, no Telegram.
- **Manual full without delivery:** `smoke=false`, `send_telegram=false`; full report artifact, no observation-history mutation.
- **Manual full with delivery:** `smoke=false`, `send_telegram=true`; verifies the destination, prepares a full report and sends immediately.
- **Scheduled:** full scan beginning at 07:30 Israel time, delivery at/after 08:00, using this repository's secrets and history.

All controls are in this repository's **Daily News Sentiment Opportunities** workflow. The manual defaults do not send messages, and smoke runs never send even if delivery is selected. After updating application code, run offline tests and a no-send live check. The schedule executes the latest default-branch commit; no external pins or caller updates are needed.

## Storage and costs

Source bodies are kept only in memory. Reports contain short headlines, source links and metadata, not full copied articles. Artifacts expire after seven days. The history cache is a convenience, not durable archival storage. This application is configured for free standard runners on public repositories and local CPU inference; it does not invoke paid hosted models or premium data endpoints.
