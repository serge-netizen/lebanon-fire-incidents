# Build plan

How `BRIEF.md` gets built, task by task, and every choice made along the way that the brief did
not make. **Anything marked _chosen_ is a judgement, not a measurement**; it says why, and it can
be changed.

Last updated: 2026-10-22 (task 2, gazetteer; first look at the real sources, §8).

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
Working since 2026-10-22: the crawl checks the private repo out on every run. The token expires
2027-10-22; when it does, the crawl fails visibly until it is renewed.

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

### Task 2 — Gazetteer ✅ (2026-10-22)
- `data/gazetteer/lebanon.parquet`, built from OCHA's table (`cod-ab-lbn`, now **CC BY-IGO**):
  8 governorates, 26 districts, 1,545 cadastral areas (+65 disputed strips, never matched), each
  with Arabic and English name, P-code and OCHA's centre point. Provenance in `SOURCE.md`.
- `crawler/geocode.py` resolves place text with six rules, written at the top of the file: exact
  names after normalisation (no fuzzy matching); common-word names need a place cue; a district
  name beats a same-named village; a governorate/district name clash resolves to what is certain;
  several candidates resolve **upward** to what they share; no known name gives `unknown`.
- `aliases.csv`: 60 rows (spellings, French/English names, cities spread over several cadastral
  areas, colloquial regions). 42 `verified`, 18 `proposed` — **a Lebanese reviewer should read the
  proposed ones** (e.g. "الجنوب" covering two governorates).
- `common_words.csv`: 60 names that are also ordinary words ("عين", "مزرعة", "غابات", "صور" in
  "بالصور"), most found by running the resolver over 998 real Lebanon24 headlines and reading
  every match.
- Done test: **36 real place strings** (NNA, Lebanon24, a Civil Defense statement) resolve as
  decided beforehand; 74 tests in all. _The brief asked for 100 seeded aliases; there are 60,
  because each one has to be true — volume will come from task 3's real place strings._
- Nine governorates (owner's decision 2026-10-22): Keserwan-Jbeil applied over OCHA's eight from
  `governorates.csv`, as code `LBKJ`; OCHA's own assignment kept as `ocha_adm1_pcode`.

### Task 3 — Tier 1 adapters
- One class per outlet on the `Source` contract (`crawler/sources/base.py`), each with a saved
  page in `fixtures/` so parser tests run offline and a parser break shows up as a red test.
- Shared polite fetcher: robots.txt honoured, 1 request/second per host, `Cache-Control: no-cache`.
- Seen-URL state in the private store, so a URL is fetched once across runs.
- NNA: discovery needs no browser (its daily sitemaps carry the headline in each address);
  article text still needs Playwright, in its own job step.
- **The source list needs revising before this task starts — see §8.** Google News is no longer a
  fallback: its robots.txt forbids it.

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
| Crawl at 03:17, 10:17, 17:17 UTC | GitHub cron has no time zones; 17 minutes past avoids GitHub's busiest moment (§8). Beirut times in summer, one hour early in winter |
| Repo name `lebanon-fire-incidents` | Neutral, says what it is |
| Commit author = GitHub no-reply address | Keeps any personal or company e-mail out of a public history |
| Fonts self-hosted (IBM Plex Sans + Plex Sans Arabic) | No third-party font request; faster; brief's first suggestion |
| Arabic and French UI strings drafted by the model | **Need a native speaker's review before launch** |
| Schema adds `schema_version`, `summary`, `official_record_id`, `sources[].raw_ref` | Versioning (task 9), our own one-line summary (§11), linking (§7), traceability |

## 6. Waiting on the owner (in the order they block work)

| # | What | Needed by | Time |
| --- | --- | --- | --- |
| 1 | ~~`PRIVATE_DATA_TOKEN` secret~~ **done 2026-10-22**: verified by a crawl run that checked out the private repo. Renew before it expires on 2027-10-22 | task 3 | done |
| 2 | ~~8 or 9 governorates~~ **decided 2026-10-22: nine** (Keserwan-Jbeil separate) | task 5 | done |
| 3 | Anthropic API key as the `ANTHROPIC_API_KEY` secret, with a monthly spend cap set in the Anthropic console | task 4 | 5 min |
| 4 | A person to hand-label the 50-article golden set | task 4 | ~2–3 h, _estimated_ |
| 5 | Google service account + its key as a secret; the review Sheet shared with it | task 5 | 15 min |
| 6 | The reviewer: who, and roughly how much time a day | task 5 | a decision |
| 7 | The manual Civil Defense Facebook log, kept for the same 14 days as the pilot run | task 5 | daily, minutes |
| 8 | Cloudflare account and the repo connected (root `site`, build `npm run build`, output `dist`) | task 7 | 10 min |
| 9 | Disclosure/brand and the domain name | launch | a decision |
| 10 | A native speaker to review the Arabic and French interface text, and the `proposed` aliases | launch | ~1 h |

## 7. Worth knowing

- The US is replacing NFIRS with a new system, NERIS. NFIRS codes stay a sound, documented
  taxonomy for this purpose, but the methodology page should say which one we use and why.
  _Verify the NERIS rollout status before writing that page._

## 8. The sources, as found on 2026-10-22 (measured, from this machine, not from GitHub's)

Collected while finding real place strings for task 2. One look each: re-test from GitHub's
servers in task 3, because sites treat data-centre addresses differently.

| Source | Brief said | Found |
| --- | --- | --- |
| Elnashra (tier 1, "highest density") | server-rendered tag pages | **Blocked by a bot check** (Cloudflare "Just a moment…", HTTP 403) on tag pages and the sitemap. We do not get around bot checks. |
| Civil Defense website (tier 1, official) | per-incident statements by sequential ID | **Newest statement dated 30 Sep 2026** (22 days old). The article address in the brief returns the full listing page, not the statement; the listing's dates are unreliable. Needs real parsing work. |
| NNA (tier 1) | sitemaps + Playwright | **Works.** Daily sitemaps per category, headline in the address. Local news, 7 Sep–21 Oct: **1,641 headlines, about 8 individual fires**; the daily Civil Defense tally appears almost every day. |
| Lebanon24 (tier 1) | ~80 items/day RSS | Two feeds: 999 items over 35 days, **3 fire headlines**. |
| Lebanon Debate (tier 1) | listing pages | **Now built in the browser**: the HTML holds no article list. Needs Playwright. |
| LBCI, Al Jadeed (tier 2) | RSS | Feeds work but hold only the last **10–20 items** (one to two days); use their news sitemaps. |
| Google News (tier 2 catch-all) | RSS search | **robots.txt forbids all automated access** (and names Claude's crawlers). Dropped. |

**What it means.** The reported stream of individual fires is thinner than the brief assumed
(the brief planned on 30–80 articles a day passing the filter). Two consequences:
- Cost (§4) will be lower than estimated — volume is the reason, not price.
- **Coverage is the real risk.** The Civil Defense daily tally (71–176 missions a day in Sep–Oct)
  will dwarf the number of fires we can find in the news. The methodology page must say this
  plainly, and the official-data request (brief §7) matters more than the brief implies.

**GitHub's schedule is late.** The crawl was set for 03:00, 10:00 and 17:00 UTC. Measured over
12 days: runs started **3 to 7 hours late**, and about one run in eighteen never ran. Task 2
moves the schedule off the top of the hour (GitHub's busiest moment); task 3 must make discovery
catch up on missed runs by reading sitemaps by date, not "latest" listings.
