# Architecture and evidence boundaries

## Components

| Component | Responsibility | Does not do |
| --- | --- | --- |
| Agent session | Open sources, assess fit, tailor material, operate browser | Invent missing personal facts |
| `flow.py` | Application packet lifecycle, fingerprints, retry holds, answer/site memory | Submit forms or authenticate accounts |
| `manage.py` | Validate and append events, summarize outcomes | Infer receipts or human responses |
| `export_sheet.py` | Build a local XLSX/CSV view, check submitted PDF hashes | Publish or send the workbook |
| `jev.py` | Optional finite-choice field mapping | Write freeform answers or authorize actions |
| External scheduler | Start fresh research sessions | Supply reliable state without reading local files |

## Local data

`JOB_SEARCH_HOME` defaults to `private/job-search/`. Its parent holds the reviewed `WORK_DOSSIER.json`. Candidate facts go in `profile.json`; exclusions go in `policy.json`. Empty exclusions mean no employer/title exclusions, not unrestricted authorization to apply.

Each `applications/<id>/` directory contains a captured JD, eligibility evidence, preparation JSON, copied PDF, readback and receipts. SHA256 fingerprints connect verification to the exact profile and PDF. Profile changes invalidate reusable answer memory. A failed site method is removed from the successful-method lookup.

`events.jsonl` is append-only. File locks prevent concurrent appends from interleaving. Submission intent is durably written before the external click. Unknown results retain a hold. Discovery deduplicates canonical URLs; preparation prevents further applications to a company with a confirmed or unresolved submission. Company-name normalization is heuristic, not a legal-entity registry.

`research/sources.jsonl` records opened sources, evidence type and limitations. `changes.jsonl` records strategy changes with baseline, evidence, review window and rollback. These research files are maintained by the agent; there is no automatic source-quality scorer.

## Limits

This is a single-user local workflow. The event ledger is not tamper-proof or encrypted. Anyone with file access can change it. The process trusts operator-provided evidence. Generic event validation is weaker than the application lifecycle checks, so use `flow.py` for application transitions. A resume hash proves byte identity, not truthful content or successful upload.

Browser execution, outreach approval and external receipts require actual observation. Only public ATS listing GET endpoints are supported; this is not an employer-side submission API client. A scheduler must enforce its own time/query budget and model-spend rules. There is no production web service in this release.

## Recovery

1. Wrong or missing field: fix the browser value and capture a new readback.
2. Changed profile/PDF: prepare again and reverify.
3. Timeout after Submit: record `unknown`; reconcile before any retry.
4. Confirmed absence of submission: resolve as `not_submitted`, then reverify before another intent.
5. Workbook failure: regenerate the workbook; never submit again to repair a report.
6. New evidence contradicts a research claim: append a correction with a source, preserving the earlier record.
