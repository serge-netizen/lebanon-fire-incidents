# Lebanon Fire Incidents — project brief for Claude Code

This is the project brief. It is the complete context needed to build the first version.

> **Amendments (2026-10-10, scaffold session).** Where this copy differs from the original brief:
> 1. **Sponsor name removed** (§2.3) — the repo is public and brand-neutral.
> 2. **Models** — extraction uses **Claude Haiku 5.5** (`claude-haiku-5-5`), as the original brief said; the second pass uses **Claude Sonnet 5.5** (`claude-sonnet-5-5`). _Corrected 2026-10-23: on 2026-10-10 this copy wrongly "corrected" the brief to Haiku 4.5 — Haiku 5.5 was newer than the reference used then._
> 3. **Private store** (§4.3, §5) — raw article text, run state, rejected items and received official files live in a separate **private** store (`private/`, a second, private repo in CI), never in this public repo. A public repo cannot hold anything privately. See `docs/BUILD_PLAN.md` §2.
> 4. **Boundaries dataset** (§4.6, §12, 2026-10-22) — the HDX dataset is now `cod-ab-lbn`, licensed **CC BY-IGO** (republishing allowed with attribution). The licence question in §4.6 is settled.
> 5. **Google News dropped** (§3 tier 2, 2026-10-22) — its robots.txt forbids all automated access, and this brief requires respecting robots.txt. Other source findings: `docs/BUILD_PLAN.md` §8. Decisions already taken are marked **DECIDED**; everything else is open to engineering judgement.
> 6. **Nine governorates** (§6 `admin1`, owner's decision 2026-10-22) — the site follows current law: Keserwan-Jbeil (2017) is its own governorate. OCHA's table has eight; the ninth is applied over it (`data/gazetteer/governorates.csv`).
> 7. **Civil Defense does publish a breakdown** (§1, §7; found 2026-10-22) — its daily bulletin lists fires put out by type (electrical, homes, grass, rubbish, vehicles…). §7's `daily_tallies` series is therefore a daily fire count by type, not just a mission count. See `docs/BUILD_PLAN.md` §9.
> 8. **History: the last 12 months** (§4 backfill, §10 task 6; owner's decision 2026-10-22) — instead of 24 months first.
> 9. **War-related fires, and how a fire is classified** (§6; owner's review 2026-10-23) — fires caused by armed hostilities (strikes, shelling, munitions, fires set by an army, military detonations) are **logged but not displayed**, where §6 had them shown separately. Each fire answers separate questions — the site (the facility or place that witnessed it), what burned, the hazard, the origin — and every value is either **reported** (read in the article) or **deduced** (looked up in a fixed table), never mixed. The lists are in `crawler/taxonomy.yaml`; they replace §6's `property_class`, `occupancy_detail` and `cause_reported` when the published schema is fixed (task 5).

---

## 1. What we are building

A public, trilingual (Arabic / English / French) statistics website that tracks fire incidents in Lebanon, compiled from news reports and official press statements, categorised with the US NFIRS taxonomy, and published with downloadable open data and a transparent methodology. Lebanon first; the pipeline must be country-agnostic so Egypt and the UAE can be added later.

The site is an authority reference, not a news site. Think CAL FIRE's incidents page meets the Gun Violence Archive's methodology page, with the visual quality of a modern data product (Linear, Vercel analytics, Our World in Data), not a government portal.

**Why it exists:** Lebanon has no public fire statistics. Civil Defense performs 35,000+ missions a year but publishes no breakdown. The only official fire numbers reach the public through press quotes. This site builds the missing record from what is reported, says so honestly, and is designed to absorb official data the day it becomes available.

## 2. Decisions already taken (DECIDED)

1. **Zero-cost infrastructure.** Public GitHub repo (free unlimited Actions minutes), static data files in the repo, Cloudflare Pages hosting, client-side charts. No paid database, no paid host. Only cash costs: domain (~$11/year) and Claude Haiku extraction (~$0.50/month).
2. **Taxonomy = US NFIRS**, simplified for display. Incident-type codes stored per record (100-series fires), with a Lebanon-specific `origin` field (accidental / deliberate / conflict-related). Details in §6.
3. **Brand-neutral build.** Whether and how the sponsor appears is undecided. Nothing in the code, domain, design tokens, copy or repo name may reference the sponsor. The About page is a placeholder. Design the "funding statement" slot so it can be filled later.
4. **Official data readiness.** The schema and site must accept official Civil Defense records (bulk CSV, scanned registers, or a future API) as a separate, reconcilable series without rework. Details in §7.
5. **No victim names, ever.** Counts only. Names are dropped at extraction.
6. **Visual bar is high.** "Nicer than USFA" is the floor. See §9.

## 3. Sources (audited 9 Oct 2026)

Almost every small fire item originates with the Civil Defense press office and the National News Agency (NNA); private outlets relay it. So the pipeline deduplicates by upstream source, not by outlet count.

### Tier 1 — crawl from day one

| Outlet | Discovery method | Notes |
| --- | --- | --- |
| **Civil Defense press statements** (official) | `http://civildefense.gov.lb/index.php?mact=News,cntnt01,detail,0&cntnt01articleid={id}&cntnt01returnid=110`, sequential IDs (~19292→19736 during Jun–Sep 2026); yearly archive pages `index.php?page=dailyacts`, `page=2025-5`, `page=2024-5`, … back to 2014 | Per-incident statements (rescues, fires) mixed with ceremonies. Generic titles — body must be read. Server-rendered CMS Made Simple. Use `http://` non-www; www blocks bots. **Mark as `source_type=official`.** |
| **Elnashra** | Tag pages `https://www.elnashra.com/news/tag/حريق` and `/news/tag/الدفاع+المدني` (40/page, dated); sections `/category/show/news/20/متفرقات`, `/37/قضاء-وأمن`; `/sitemap.xml` (rolling 375 URLs, slug = headline) | Highest density of small fires with town + قضاء. No RSS. Server-rendered. |
| **Lebanon24** | RSS `https://www.lebanon24.com/Rss/News/1/لبنان` (~80/day), `/Rss/News/23/أخبار-عاجلة`, `/Rss/News/7/متفرقات`; `newssitemap.xml` backstop | Breaking items sometimes headline-only; hold cluster until a fuller source arrives. |
| **NNA** (nna-leb.gov.lb) | Sitemap index → `/ar/sitemap/news.xml` → category indexes → per-day `/ar/sitemap/n/{cat}?date=YYYY-MM-DD` (loc + lastmod only; decode Arabic slug for title). RSS `/ar/rss` exists but is stale — do not rely on it. | **JavaScript-rendered (Next.js)** — article text needs Playwright. `/api/` is robots-disallowed; do not call it. Carries the Civil Defense daily tally ("الدفاع المدني: 125 مهمة خلال الـ24 ساعة الماضية") — capture as `aggregate_report`, never as an incident. |
| **L'Orient Today** (EN) | `https://today.lorientlejour.com/live-news?pagination=N` (12/page), `/sitemap/latest_articles` | Best English source for small incidents; bodies may be paywalled, headlines are not. FR site (lorientlejour.com) blocks crawlers — skip. |
| **Lebanon Debate** | `https://www.lebanondebate.com/category/134-المحلية`, `/178-أمن-وقضاء`, `/223-على-مدار-الساعة`, `?pagination=N` | 2–3 fire headlines per 24-item page in sample. No RSS. |

### Tier 2 — add in week 2

| Outlet | Discovery |
| --- | --- |
| LBCI | RSS index `https://www.lbcgroup.tv/rss/ar` → `Rss/latest-news/ar`, `Rss/News/ar/3/أمن-وقضاء`, `Rss/News/ar/1/أخبار-لبنان`; `newssitemap.xml` |
| Al Jadeed | `https://www.aljadeed.tv/rss/ar` → `Rss/latest-news/ar`, `Rss/News/55/أخبار-لبنان/ar`; `newssitemap.xml` |
| MTV | `https://sitemaps.mtv.com.lb/fresh/sitemap-news.xml.gz` (Google News format, has titles); `/news/محليات`; monthly archives `archives/{YYYY}/sitemap-{YYYY}-m{M}.xml.gz` back to 2011 (backfill) |
| Tayyar.org | `/sitemap.xml` (news format with titles); `/news/Lebanon` |
| Kataeb.org | `/category/متفرقات`, `/category/مناطق`, `/category/أمن-وقضاء` (undated listings; dedupe by slug) |
| Janoubia (South) | WordPress RSS `https://janoubia.com/feed/`; `/category/عامليات/` |
| Annahar | `/sitemap/sitemap-news.xml`; monthly `sitemap-YYYY-MM.xml` back to 1997 (backfill) |
| Google News RSS | `https://news.google.com/rss/search?q=حريق+لبنان&hl=ar&gl=LB&ceid=LB:ar` (+ `"الدفاع المدني" حريق`, `إخماد حريق`, each with `when:1d`) — catch-all; **untested from our side, test first** |

### Tier 3 / skip

Lebanonfiles (bot-challenged; retry with browser UA, else via Google News), OTV (`/latest` needs Playwright), Al Akhbar, Naharnet, Sawt Beirut, the961, Libnanews — low density. Skip: L'Orient-Le Jour FR, Red Cross (feed dead since 2021), Akkar Network (blocks bots). **Do not scrape Facebook or X** (terms); the Civil Defense Facebook page is a manual recall check only.

### Crawl etiquette
Respect robots.txt; browser user-agent; `Cache-Control: no-cache` (several listing pages served stale cached copies); 1 request/second per host; three scheduled runs a day (06:00, 13:00, 20:00 Beirut). A full run should touch a few hundred URLs, not thousands.

### Keyword filter (headline + first 300 chars)
Match: `حريق|حرائق|اندل(ع|اع) حريق|إخماد|أخمد|تخمد|النيران|نيران تشتعل|اشتعال|احتراق|حرقاً|حرقًا|التهمت|تلتهم|السيطرة على الحريق|احتواء حريق|تجدد الحريق|بؤرة|فوج (إطفاء|الإطفاء)|الدفاع المدني|ماس كهربائي|قارورة غاز|مولد|حالات اختناق`
EN: `fire (broke|breaks) out|blaze|brought under control|extinguish|Civil Defense|asphyxiation|gas canister`
FR: `incendie|feu (s'est déclaré|a éclaté)|maîtrisé|défense civile`
Exclude: `نيران العدو|تحت نيران|إطلاق نار|قصف` (military fire — but keep if a civilian fire resulted; let the model decide), `تشعل الغضب|يشعل جدلاً` (figurative), `نشرة إحتمال إندلاع حرائق|موجة الحر` (risk bulletins), foreign datelines.

## 4. Pipeline

```
discover → filter → fetch → extract (Haiku, Batch API) → dedupe → geocode → review → publish
```

1. **Discover.** Per-source adapter returns `(url, headline, published_at, source)`. Store seen URLs in the private store (`private/state/seen_urls.parquet`). Adapters live in `crawler/sources/{slug}.py`, one class each, with a `discover()` and `fetch(url)` method and a test fixture of a saved HTML page.
2. **Filter.** Regex above over headline and lead. Borderline (`انفجار`, `دخان`, `اختناق`) passes to the model.
3. **Fetch.** `httpx` + `trafilatura` for all sites; Playwright (`npx playwright install --with-deps chromium` in the Actions job) only for NNA and OTV. Store raw text in the private store, `private/raw/{source}/{yyyy-mm}/{hash}.json` (git-tracked in the **private** repo; article bodies never appear publicly).
4. **Extract.** Claude Haiku 5.5 (`claude-haiku-5-5`) via the Batch API (half price, results within an hour). One request per article, structured output enforced with a JSON schema (§6). Prompt rules: an article may contain several incidents (roundups) — return a list; `null` when the text does not say; quote verbatim evidence for every non-null field; never output personal names; distinguish `incident` from `aggregate_report` (daily tallies, seasonal totals) from `not_a_fire`. Send low-confidence (`confidence < 0.7`) or casualty-bearing records to a second pass with Claude Sonnet 5.5 (`claude-sonnet-5-5`).
5. **Dedupe.** Cluster key: same `admin2` (district) + same `incident_group` + `occurred_at` within 36 h + fuzzy match on place string. A cluster = one incident with many `sources[]`. Conflicting casualty counts → `needs_review`. Prefer official (Civil Defense) values when present.
6. **Geocode offline.** `data/gazetteer/lebanon.parquet` built from the OCHA/CDR admin boundaries (levels 0–3, HDX: `lebanon-administrative-boundaries-levels-0-3`; licence listed as "Other" — use for the internal table, confirm before redistributing shapes) plus a hand-maintained alias table (`gazetteer/aliases.csv`: Arabic, French, English spellings, common misspellings). Resolve to the finest level matched; record `location_precision` (village / district / governorate / unknown). No external geocoding API. Nominatim only as a manual helper for the alias table.
7. **Review.** Append new/flagged incidents to a Google Sheet (service account; free API) with columns = schema + `decision` (approve / edit / reject) + `reviewer_note`. The next run reads decisions back. Rejected items are kept privately so they are not re-proposed. Target: ≤ 1 minute per incident.
8. **Publish.** Approved incidents → `data/published/incidents.parquet` + `.csv` + `.geojson`; aggregates recomputed into small JSON files (`by_month.json`, `by_governorate.json`, `by_type.json`, `by_cause.json`, `kpi.json`); commit; Cloudflare Pages rebuilds.

**Backfill:** same adapters pointed at archives (MTV and Annahar monthly sitemaps, NNA daily sitemaps back ~410 days, Elnashra tag pagination, Civil Defense yearly archive pages back to 2014, Wayback CDX API for gaps). Target 24 months first, then extend. Budget: ~$3–6 of Haiku Batch per 20,000 articles.

## 5. Repo layout

```
BRIEF.md  CLAUDE.md  README.md  LICENSE (code: MIT; data: CC BY 4.0)
crawler/            Python 3.12, uv-managed
  sources/          one adapter per outlet + fixtures/
  filter.py  fetch.py  extract.py  dedupe.py  geocode.py  review.py  publish.py
  prompts/extract.md
  schema/incident.schema.json
data/
  gazetteer/        lebanon.parquet, aliases.csv
  published/        incidents.{parquet,csv,geojson}, aggregates/*.json, DATA_DICTIONARY.md, CHANGELOG.md
  official/         mapping/*.yaml and derived official series (§7); received files go to private/official/
private/            gitignored here; in CI a checkout of the private data repo (raw/, state/, rejected/, official/)
site/               Astro (static) + TypeScript; charts with Observable Plot; map with MapLibre GL + free OSM tiles; DuckDB-WASM for the explorer
  src/content/      methodology, definitions, about (MD, trilingual)
.github/workflows/  crawl.yml (cron 3×/day), backfill.yml (manual), build.yml, keepalive.yml (monthly commit so cron is never auto-disabled after 60 days)
```

## 6. Data model (NFIRS-based)

`schema/incident.schema.json` — one record per incident:

| Field | Type | Notes |
| --- | --- | --- |
| `id` | string | `LB-YYYYMMDD-NNNN` |
| `country` | string | ISO-2, `LB` |
| `record_type` | enum | `incident` / `aggregate_report` / `not_a_fire` |
| `occurred_at` | date-time | best estimate; `date_precision`: `exact` / `day` / `week` |
| `reported_at` | date-time | earliest source publish time |
| `incident_group` | enum | `fire` / `explosion` / `false_or_unconfirmed` |
| `nfirs_type` | int | NFIRS 100-series: 111 building, 113 cooking fire confined, 118 trash in structure, 130/131/132 vehicle, 140/141/142/143 vegetation (natural/forest/brush/grass), 150/151/154 outside rubbish, 160 special outside, 100 other |
| `property_class` | enum | residential / commercial / industrial_warehouse / public_institutional / vehicle / outdoor_wildland / informal_settlement / fuel_energy (generator rooms, fuel stations) / other |
| `occupancy_detail` | string | free text as reported ("sponge factory", "café") |
| `cause_reported` | enum | electrical / generator_fuel / cooking / heating / smoking / open_flame / intentional / gas_leak / military_strike / under_investigation_unknown (default) |
| `origin` | enum | accidental / deliberate / conflict_related / unknown — **always shown separately**; conflict fires must never silently inflate safety trends |
| `deaths`, `injuries`, `asphyxiation_cases`, `displaced` | int / null | counts only |
| `structures_destroyed` | int / null | |
| `responders` | array | `civil_defense`, `beirut_fire_brigade`, `army_helicopters`, `red_cross`, `other` |
| `severity` | int 1–4 | 1 extinguished on arrival / 2 damage, no casualties / 3 injuries or displacement / 4 deaths or multiple structures |
| `place_text` | string | as written |
| `admin1`, `admin2`, `admin3` | string + pcode | governorate / district (caza) / cadastral village from OCHA table |
| `lat`, `lon` | float / null | centroid of the finest matched admin unit; `location_precision` enum |
| `sources[]` | array | `{outlet, url, headline, published_at, source_type: media|official, is_upstream: bool}` |
| `evidence{}` | object | verbatim quotes per populated field |
| `confidence` | float | model self-assessment, then reviewer override |
| `status` | enum | auto / needs_review / approved / rejected |
| `tags[]` | array | multi_fatality, child_casualty, refugee_settlement, forest_fire_season, … |
| `created_at`, `updated_at`, `revision_note` | | public correction history |

Published CSV omits `evidence` and raw text; everything else is public.

## 7. Official-data readiness (Civil Defense and others)

Status as of 9 Oct 2026, verified on their site: Civil Defense publishes **no statistics**. The "annual report" PDF is a 2021 strategy draft with no numbers. What they do publish is per-incident press statements (Tier 1 above) and, via NNA, a daily 24-hour mission count. A data-sharing request is the only route to their full mission log; assume it will arrive, if at all, as an Excel export or scanned register with their own categories.

Build so that this needs no refactor:

- `data/official/` holds imports as received, plus a `mapping/{source}.yaml` that maps their categories to NFIRS codes and their place names to the gazetteer.
- Every incident carries `source_type` on each source; an official record and a media cluster describing the same event are **linked, not merged**: `official_record_id` on the media incident, and a `reconciliation` table listing matched / official-only / media-only.
- The site shows two series when both exist: "Reported in media" and "Official (Civil Defense)", plus a coverage ratio (media ÷ official) on the methodology page — the number that turns a tracker into a statistic.
- The `aggregate_report` record type already captures the NNA daily tally; a `data/official/daily_tallies.csv` series starts on day one from those.
- Provide an `import_official.py` CLI that validates a CSV against the schema, applies the mapping, and writes a reconciliation report.

## 8. Site

Astro static site, trilingual with `/ar` (RTL), `/en`, `/fr`; language switch keeps the page. All charts render client-side from the aggregate JSON; the explorer and map use DuckDB-WASM over `incidents.parquet`. Every chart has: table toggle, PNG download, CSV of its data, source line, and a URL that encodes its state (`?year=2026&gov=north&type=residential`).

| Page | Content |
| --- | --- |
| Home | 5 KPI tiles (YTD reported fires, deaths, injuries, structure fires, vs same period last year); "a fire is reported every X hours"; 12-month sparkline; governorate map; last-7-days feed; "data as of" stamp; "compiled from news and official statements" badge |
| Explorer | Filterable table (date range, governorate/district, type, property class, cause, origin, casualties, source outlet, status) → incident page (facts, all source links, update timeline, map pin, corrections) → filtered CSV export |
| Map | Points + choropleth (counts and per 100k), layers by property class, year slider |
| By governorate `/governorate/{slug}` | KPIs, rate per 100k, trend, type mix, top districts, recent incidents |
| By type `/type/{slug}` | Definition (NFIRS), trend, cause mix, casualties per 1,000 fires, notable incidents |
| Themed views | Multi-fatality fires, generator/electrical, fuel stations, informal settlements, forest-fire season, conflict-related (shown apart) |
| Annual report `/reports/{year}` | Narrative + charts, top-10 deadliest/most destructive, YoY deltas, PDF |
| Methodology | Sources, cadence, pipeline, definitions with numeric thresholds, coverage gaps, "how we differ from Civil Defense figures", measured extraction accuracy on a labelled sample, changelog |
| Data | CSV / Parquet / GeoJSON per year and full, DATA_DICTIONARY, CC BY 4.0, citation text, chart embed snippets, schema.org `Dataset` markup |
| Recommendations | Placeholder until phase 4; visually separate from data |
| About / corrections | Placeholder funding statement slot; correction form (GitHub issue form or Google Form) |

## 9. Design direction

The reference is modern data products, not government sites. Concretely:

- **Typography:** one humanist sans with real Arabic support, e.g. IBM Plex Sans + IBM Plex Sans Arabic, or Inter + Noto Naskh Arabic for body; tabular numerals everywhere numbers align. Arabic set at 1.1× the Latin size.
- **Palette:** near-white / near-black backgrounds with a single warm accent for fire data (one hue, 5 tints for sequential scales), a cool neutral for official-series overlays, and a desaturated grey for conflict-related so it never reads as "alarm". Light and dark themes from day one via CSS tokens; prefers-color-scheme respected.
- **Layout:** generous whitespace, 12-column grid, max content width ~1200 px, KPI tiles with big numerals (48–64 px) and a small delta chip, charts with no chart junk (no gridlines heavier than hairline, no 3D, no legends where direct labels work).
- **Charts:** Observable Plot with a shared theme file; consistent axis style; hover tooltips; annotations for anomalous periods (war months, heatwaves) rendered as subtle bands with a label.
- **Map:** MapLibre with a muted basemap (e.g. OpenFreeMap "positron"), choropleth on governorate/district, point layer clustered at low zoom.
- **Motion:** 150–200 ms transitions, no autoplay animation, count-up on KPI tiles once.
- **RTL:** mirrored layout, logical CSS properties, charts keep LTR axes but RTL labels.
- Accessibility: WCAG AA contrast, keyboard-navigable filters, chart tables for screen readers.

Load the `frontend-design` and `dataviz` skills before building the site.

## 10. Work plan for Claude Code (in order)

Each item is one session-sized task with a clear "done" test. Do not skip ahead to the site before the pilot data exists.

1. **Scaffold.** Repo layout, `uv` project, Astro skeleton, Actions workflows (cron, build, keepalive), Cloudflare Pages connected, schema file, data dictionary stub. Done: `uv run crawler --dry-run` and `npm run build` both pass in CI.
2. **Gazetteer.** Download OCHA boundaries, build `lebanon.parquet` with pcodes and Arabic/English names, seed `aliases.csv` with the 100 most common Lebanese town-name variants. Done: unit tests resolving 30 sample strings from real headlines.
3. **Adapters, Tier 1.** Six adapters with fixtures: Civil Defense, Elnashra, Lebanon24, NNA (Playwright), L'Orient Today, Lebanon Debate. Done: each returns ≥ 1 real item in CI; dedupe of seen URLs works across runs.
4. **Filter + extraction.** Keyword filter with tests; Haiku Batch extraction with schema-enforced output; 50-article golden set hand-labelled; measured precision/recall logged to `data/quality/`. Done: ≥ 0.85 F1 on incident detection on the golden set, or an explicit note on why not.
5. **Dedupe + geocode + review sheet.** Clustering rules, Sheet round-trip, `status` lifecycle. Done: a 14-day run produces a reviewed `incidents.parquet` and a recall figure versus the manual Civil Defense Facebook log (the owner keeps that log).
6. **Tier 2 adapters + Google News RSS + backfill job.** Done: 24 months of history reviewed at least at the "auto" level; monthly counts plotted for sanity.
7. **Site v1.** Home, explorer, map, methodology, data pages, trilingual, dark/light. Done: Lighthouse ≥ 90 on performance and accessibility, RTL verified by screenshot, every number on the home page traceable to one aggregate file.
8. **Official import path.** `import_official.py`, mapping YAML, reconciliation report, dual-series chart component. Done: a synthetic official CSV imports and reconciles against the media series end to end.
9. **Hardening.** Parser-breakage alerts (Actions failure → GitHub issue), schema versioning, `CHANGELOG.md` for data, corrections workflow.

## 11. Rules of the road

- Public data = facts, our own one-line summary, headline, outlet, link. Never republish article text.
- Causes are always "as reported"; never attribute fault to a named business, owner or installer.
- Victim names never enter the dataset, not even in `evidence`.
- Conflict-related fires are a separate series; every aggregate offers "exclude conflict-related" and the default home view shows them apart.
- Every public number must trace to one file; no two pages may show different totals for the same thing.
- The pilot's recall figure and the golden-set accuracy go on the methodology page, whatever they are.
- Keep the repo public, keep commits flowing (keepalive job), keep Arabic strings in UTF-8 files, not in code.

## 12. Open items the owner will settle

- Disclosure / brand (decides domain and the About page).
- Reviewer (who, and the Google account for the Sheet).
- Lebanonfiles and Google News RSS reachability from Actions (test in task 3).
- Civil Defense, Ministry of Environment / Balamand and CNRS-L contacts for the data request.
- Whether to test the Lebanon Civil Defense "daily tally" series against the NNA archive back to Aug 2025 in the backfill.

## 13. References

- Earlier research: `reports/Lebanon fire incident data feasibility.md`; per-outlet audit `research_notes/Lebanon fire incident data feasibility/outlet_feed_audit.md`; stack and dashboard notes `research_notes/.../dashboards_and_free_stack.md`.
- NFIRS incident type codes: https://doi.idaho.gov/wp-content/uploads/SFM/NFIRS/ReportingTools/CheatSheets/Cheat-Sheet-Incident-Type.pdf
- OCHA Lebanon boundaries: https://data.humdata.org/dataset/lebanon-administrative-boundaries-levels-0-3
- Anthropic pricing (Haiku 5.5, Batch): https://platform.claude.com/docs/en/about-claude/pricing
- Cloudflare Pages limits: https://developers.cloudflare.com/pages/platform/limits/
- GitHub Actions billing: https://docs.github.com/en/billing/concepts/product-billing/github-actions
- Models to emulate: https://www.fire.ca.gov/incidents, https://www.gunviolencearchive.org/methodology, https://www.usfa.fema.gov/statistics/, https://apps.usfa.fema.gov/civilian-fatalities/
