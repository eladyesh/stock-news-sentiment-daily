# Source coverage

Reviewed 2026-10-16. Availability is checked on every run; the table describes configured routes, not guaranteed access.

| Family | Configured collection | What it supports | Principal limit |
| --- | --- | --- | --- |
| Nasdaq Trader | Nasdaq and other-listed symbol directories | Current exchange-listed issuer universe | Not OTC; conservative entity matching can miss names/aliases |
| Google News RSS | 24 broad sector/catalyst/source queries, up to 60 adaptive follow-ups | Broad publisher discovery and headlines | Ranked/capped results; opaque links can prevent original-page access |
| GDELT DOC API | 12 broad English queries, up to 250 results each | Many publishers and direct article links | First-seen time differs from publication; timeouts/caps are recorded |
| GlobeNewswire | 12 advertised public-company and subject RSS feeds | Direct issuer releases across catalysts | Usually a small rolling feed; issuer publicity is not independent verification |
| CNBC | Markets and earnings RSS | Direct reporting leads | Feed/window depth and article access vary |
| Yahoo Finance | General news RSS | Broad reporting leads | Throttling and publisher/syndication ambiguity |
| MarketWatch | Top-stories RSS | Reporting leads | Article access and rolling-feed depth |
| Reddit | Seven configured communities, up to 100 recent posts each | Observed social discussion sample | Rate limits, bots, community bias, sarcasm; not all Reddit |
| Bluesky | Four English public searches, up to 100 posts each | Observed public-post sample | Search can require authorization or refuse access |

GlobeNewswire feeds were selected from its published RSS catalog, rather than assuming undocumented endpoints. Broad news queries include Business Wire, PR Newswire, SEC, clinical, earnings, contracts, capital structure, legal, sector and small-cap discovery. A returned headline is not an original-source read.

## Primary documentation

- [Nasdaq symbol-directory definitions](https://www.nasdaqtrader.com/trader.aspx?id=symboldirdefs)
- [Nasdaq-listed symbols](https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt)
- [Other-listed symbols](https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt)
- [GlobeNewswire RSS catalog](https://www.globenewswire.com/Rss/List)
- [GDELT DOC 2.0 API](https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/)
- [Bluesky searchPosts reference](https://docs.bsky.app/docs/api/app-bsky-feed-search-posts)
- [Financial sentiment model card](https://huggingface.co/mrm8488/distilroberta-finetuned-financial-news-sentiment-analysis)
- [Telegram Bot API](https://core.telegram.org/bots/api#sendmessage)
- [GitHub schedule events, timezones and limitations](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)
- [GitHub standard hosted runners](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)

## Model provenance

Model: `mrm8488/distilroberta-finetuned-financial-news-sentiment-analysis`.

Pinned revision: `ae0eab9ad336d7d548e0efe394b07c04bcaf6e91`.

The model card identifies an Apache-2.0-licensed DistilRoBERTa financial-news classifier. Inference uses `safetensors`, `trust_remote_code=False`, three labeled probabilities and English-language filtering. Training-domain performance does not establish predictive investing accuracy or social-media reliability. The project does not retrain or claim to calibrate the model.

## Deliberate gaps

- No full X/Stocktwits firehose, private groups, private chats, or authenticated account access.
- No complete global coverage or claim to read every listed company's daily disclosures.
- No automated verification of exact political quotes, speaker identity, edited videos or screenshots. Such claims remain attributed/unverified.
- No unsupported beat/miss calculation, valuation target, pre/post-event return or causal stock-price attribution.
- No historical backfill presented as an observed daily baseline.
- No known bot-removal guarantee or inference from missing social data to lack of discussion.
