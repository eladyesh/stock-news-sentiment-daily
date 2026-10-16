# Operations

## Deploy with the existing Telegram credentials

1. Create public repository `eladyesh/stock-news-sentiment-daily` and push this project to `main`.
2. Wait for the offline Tests workflow to pass. Manually dispatch **Daily News Sentiment Opportunities** with `smoke=true` and `send_telegram=false` to check hosted-runner access.
3. Copy `examples/telegram-caller.yml` into `eladyesh/stock-screener-daily/.github/workflows/daily_news_sentiment.yml`. Pin both `uses` and `code_ref` to the same reviewed commit in the new repository.
4. Manually dispatch **Daily News Opportunities to Telegram** in the existing repository. It verifies the private destination, performs a full scan and delivers the report immediately. Scheduled runs wait for 08:00 Israel time.
5. Check the delivery step and the private chat. Check the report artifact's coverage ledger as well: workflow success alone does not mean every source was accessible.

The two existing secrets stay in `stock-screener-daily`. The caller passes only `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`. The new repository has no need to know their values. Do not copy credentials into a workflow, issue, README or commit.

## Daily state

`state/state.json` contains seven days of comparable aggregate observations, seen-headline hashes and the delivery cursor. `state/pending_report.json` is the exact day's report. Both are ignored by git and restored from/saved to an Actions cache scoped to the caller repository.

The cache key changes for each run and attempt, restoring the most recent prefix match. Concurrent news runs are serialized. Cache misses deliberately reset history; the report must not claim acceleration until a comparable baseline exists again.

The sender requires the report's local date to match today and its generation time to be no more than six hours old. Research preparation is reused on same-day retries. A manual delivery counts as that day's report, so a later scheduled retry does not intentionally send a second edition.

## Investigate failures

| Symptom | Where to look | Recovery |
| --- | --- | --- |
| Missing Telegram secret | Verification-step error | Check secret names in the caller repository; do not print values |
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

- **New repository / manual smoke:** limited access check, no Telegram.
- **New repository / manual full with send disabled:** full report artifact, no observation-history mutation.
- **Existing repository / manual caller:** full report; `send_telegram=false` is an explicit dry run.
- **Existing repository / scheduled caller:** starts 07:30 Israel time, sends at/after 08:00.
- **Standalone opt-in:** only when the caller is disabled and the two secrets exist in the new repository.

After updating application code, run offline tests and a no-send live check, then update both pinned references in the caller. Do not change only one pin: the reusable workflow and checked-out application must come from the same reviewed commit.

## Storage and costs

Source bodies are kept only in memory. Reports contain short headlines, source links and metadata, not full copied articles. Artifacts expire after seven days. The history cache is a convenience, not durable archival storage. This application is configured for free standard runners on public repositories and local CPU inference; it does not invoke paid hosted models or premium data endpoints.
