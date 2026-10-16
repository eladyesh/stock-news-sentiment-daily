# Validation record

Validation date: 2026-10-16. These checks sent no Telegram messages.

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

## Deployment checks still required

At packaging time, repository creation was blocked by the GitHub browser sign-in requirement. The following are not yet verified:

- Repository creation and remote upload.
- Hosted GitHub Actions execution.
- Installation of the scheduled caller in `stock-screener-daily`.
- Telegram verification using that repository's encrypted secrets and actual delivery.

The application, tests and workflows are complete for that deployment step. No schedule is claimed to be active merely because a workflow file exists locally.
