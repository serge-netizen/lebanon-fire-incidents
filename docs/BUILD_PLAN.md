# Build plan

How `BRIEF.md` gets built, task by task, and every choice made along the way that the brief did
not make. **Anything marked _chosen_ is a judgement, not a measurement**; it says why, and it can
be changed.

Last updated: 2026-10-10 (task 1, scaffold; private store and review tool decided).

---

## 1. The shape of the system

```
                    ┌──────────── PUBLIC repo (this one) ────────────┐
  outlets ──► crawler (GitHub Actions, 3×/day)                       │
                │  discover → filter → fetch → extract → dedupe       │
                │  → geocode → review → publish                       │
                │                                   │                 │
                │                                   ▼                 │
                │                       data/published/*  ──► Cloudflare Pages
                │                       (open data + aggregates)      (static site)
                └───────────────────────────────────────────────────┘
                │ reads/writes
                ▼
        PRIVATE repo  ── raw article text, seen URLs, extraction output,
                         evidence quotes, rejected items, official files as received
```

- **Two stores, one rule:** anything we may not republish lives in the private store.
  Everything public is derived from it and can be rebuilt from it.
- **Every data point traces back:** incident → `sources[].raw_ref` → the article text in the
  private store → the original URL. This is what "the source data behind every data point" means
  in practice.
- **No servers, no database.** GitHub Actions does the work; files are the database; Cloudflare
  Pages serves the site.

## 2. The private store — DECIDED 2026-10-10: a second, private GitHub repo

Created: `serge-netizen/lebanon-fire-incidents-data` (private). Its name is the Actions
variable `PRIVATE_DATA_REPO`; the access token is the secret `PRIVATE_DATA_TOKEN`, created by the owner.

The brief said raw text is "git-tracked but not published". In a public repo, git-tracked *is*
published. So the text needs a separate home.

| Option | Cost | Keeps source text forever | Moving parts |
| --- | --- | --- | --- |
| **A. Private GitHub repo (recommended)** | Free | Yes | One access token as an Actions secret |
| B. Hash + link only, re-fetch when needed | Free | **No** — lost when an outlet deletes or edits the article | None |
| C. Cloudflare R2 bucket | Free to 10 GB | Yes | A key pair, an upload client |

Why A: it keeps the text, it is versioned (we can see when an article was edited), it costs
nothing because the **work runs in the public repo** (unlimited minutes) and only pushes files to
the private one. Size check, _estimated_: ~3 KB of text per article × ~2,000 filtered articles a
month ≈ 6 MB a month; 24 months of backfill well under 1 GB. GitHub's soft limit per repo is
around 5 GB. Revisit if the backfill extends past 10 years.

The scaffold already treats `private/` as a path (`FIRE_PRIVATE_DIR`), so A, B or C can be
swapped without touching pipeline code. `crawl.yml` checks the private repo out only when the
`PRIVATE_DATA_TOKEN` secret exists; until then it dry-runs.

## 3. Task by task

### Task 1 — Scaffold ✅ (this session)
Repo layout, uv project, schema 1.0.0 with tests, CLI with `--dry-run`, Astro skeleton in three
languages with RTL and light/dark tokens, four workflows. **Not done: Cloudflare Pages connection**
— it needs the owner's Cloudflare account (§6).

### Task 2 — Gazetteer
- Download OCHA admin levels 0–3 from HDX; build `lebanon.parquet` with P-codes, Arabic and
  English names, centroids. Keep shapes out of the public repo until the licence is confirmed.
- `aliases.csv` maps spellings to P-codes. Seed from the most frequent place strings in real
  headlines (needs task 3 output for real frequencies, so seed a first 100 by hand, then grow).
- Matching order: exact alias → normalised Arabic (strip diacritics, unify alef/hamza forms,
  taa marbuta/haa, alef maqsura/yaa) → **exact** match on normalised forms. **No fuzzy matching of
  town names**: distinct villages differ by one letter. An unmatched string stays at the coarser
  level it does establish (a caza named in the text) or `unknown`, and is queued for the alias
  table.
- Infer upward only: a village fills district and governorate; a district never fills a village.
- Done test: 30 real headline strings resolve as expected.

### Task 3 — Tier 1 adapters
- One class per outlet on the `Source` contract (`crawler/sources/base.py`), each with a saved
  page in `fixtures/` so parser tests run offline and a parser break shows up as a red test.
- Shared polite fetcher: robots.txt honoured, 1 request/second per host, `Cache-Control: no-cache`.
- Seen-URL state in the private store, so a URL is fetched once across runs.
- NNA via Playwright in its own job step (only that step installs Chromium).
- Test reachability of Lebanonfiles and Google News RSS from Actions' US-based runners (open item).
- **Risk:** outlets may block GitHub's IP ranges. Fallback if one does: route that outlet through
  Google News RSS, which links to it.

### Task 4 — Filter + extraction
- Keyword patterns in a UTF-8 YAML file, tested against labelled headlines.
- Extraction: Haiku 4.5 on the Batch API with structured output (`output_config.format`, JSON
  schema derived from `incident.schema.json` minus server-side fields). One request per article;
  output is a **list** of items, each typed `incident` / `aggregate_report` / `not_a_fire`.
- The system prompt is identical for every request and is cached, cutting its input cost.
- Second pass on Sonnet 5 when confidence < 0.7 (_chosen in the brief_) or casualties are present.
- Names: the schema has no field that can hold one; a post-check also rejects any evidence quote
  that matches a name pattern and sends it to review.
- Golden set: 50 articles hand-labelled **by a person** (the owner or the reviewer), never by the
  model being tested. Precision, recall and F1 written to `data/quality/` (public) — the brief
  requires the figure on the methodology page whatever it is.

### Task 5 — Dedupe, geocode, review, publish
- Cluster key from the brief: same district + same incident group + within 36 h (_chosen in the
  brief_) + place-string similarity. Official values win on conflict; conflicting casualty counts
  → `needs_review`.
- Review sheet: **DECIDED 2026-10-10 — a Google Sheet**, as in the brief, on the owner's Google
  account. A service account (a robot Google user) reads and writes it; its key is an Actions
  secret created by the owner. Set up at the start of task 5.
- Publish: parquet + csv + geojson + aggregate JSON files; `DATA_DICTIONARY.md` generated from the
  schema so the two cannot drift.
- Done test: a 14-day run, reviewed, with a recall figure against the owner's manual log.

### Task 6 — Tier 2 + backfill
Same adapters pointed at archives, month by month, resumable (state in the private store), so a
run that times out picks up where it stopped. Sanity plot of monthly counts.

### Task 7 — Site v1
Load the `frontend-design` and `dataviz` skills first. Observable Plot charts from the aggregate
JSON; MapLibre + OpenFreeMap; DuckDB-WASM over `incidents.parquet` for the explorer. Every chart:
table toggle, PNG, CSV, source line, URL state. Lighthouse ≥ 90.

### Task 8 — Official import path
`import_official.py`: validate → map (YAML) → link (never merge) → reconciliation report.
Tested end to end on a synthetic official CSV.

### Task 9 — Hardening
Failed workflow → GitHub issue automatically; schema versioning; data changelog; corrections
workflow.

## 4. What it costs to run — _estimates, to be measured in task 4_

Claude prices from the current price list: Haiku 4.5 at $1 / $5 per million input / output
tokens, Sonnet 5 at $2 / $10; the Batch API halves both.

| Assumption (_chosen, not measured_) | Value |
| --- | --- |
| Articles passing the keyword filter | 30–80 a day |
| Tokens per article in | ~2,000 (Arabic text tokenises heavily) |
| Tokens per article out | ~400 (items + evidence quotes) |
| Share sent to the Sonnet second pass | ~20% |

That gives about **$0.002 per article on Haiku**, so **~$2–6 a month** ongoing and **~$40–80 for a
24-month backfill**. **This is roughly ten times the brief's figures** ($0.50 a month; $3–6 per
20,000 articles). Most of the gap is output tokens: evidence quotes are not free. Task 4 measures
the real numbers on the golden set before any backfill runs.

## 5. Choices made in the scaffold (all _chosen_, all changeable)

| Choice | Why |
| --- | --- |
| Arabic is the default language; `/` redirects to `/ar/` | The audience is Lebanese; a static site cannot read the browser's language |
| Crawl at 03:00, 10:00, 17:00 UTC | GitHub cron has no time zones. Exact Beirut times in summer, one hour early in winter |
| Repo name `lebanon-fire-incidents` | Neutral, says what it is |
| Commit author = GitHub no-reply address | Keeps any personal or company e-mail out of a public history |
| Fonts self-hosted (IBM Plex Sans + Plex Sans Arabic) | No third-party font request; faster; brief's first suggestion |
| Arabic and French UI strings drafted by the model | **Need a native speaker's review before launch** |
| Schema adds `schema_version`, `summary`, `official_record_id`, `sources[].raw_ref` | Versioning (task 9), our own one-line summary (§11), linking (§7), traceability |

## 6. Waiting on the owner

1. **Private store**: repo created; the owner creates the fine-grained token and saves it as the
   `PRIVATE_DATA_TOKEN` secret (only the owner handles tokens).
2. **Cloudflare Pages**: connect this repo in the Cloudflare dashboard — build command
   `npm run build`, root directory `site`, output `dist`.
3. **Anthropic API key** as an Actions secret, before task 4.
4. **Review tool**: Google Sheet decided; the service-account key is needed by task 5.
5. Brief §12 items: disclosure, reviewer, data-request contacts.

## 7. Worth knowing

- The US is replacing NFIRS with a new system, NERIS. NFIRS codes stay a sound, documented
  taxonomy for this purpose, but the methodology page should say which one we use and why.
  _Verify the NERIS rollout status before writing that page._
