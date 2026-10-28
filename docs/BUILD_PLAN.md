# Build plan

How `BRIEF.md` gets built, task by task, and every choice made along the way that the brief did
not make. **Anything marked _chosen_ is a judgement, not a measurement**; it says why, and it can
be changed.

Last updated: 2026-10-27 (owner's answers: history before the site; review by e-mail; drafts before
anything is published. Built the same day: classification with every crawl, outlet readers, the
12-month history collector, the review e-mail).

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
- **2026-10-27, from the first reports read in full:** rule 7, a direction is not a place
  ("نفق حامات باتجاه طرابلس" is the Hamat tunnel, not Tripoli); alias "دبعال" for Debaal (Tyre
  district), `proposed`. 39 real place strings in the done test.
- **2026-10-27, from the history check:** OCHA adds the district to 122 village names shared by
  several places ("الخرائب صيدا"), but the press writes the bare name ("الخرايب"), which resolved to
  the one village OCHA lists bare — the wrong one for the southern Kharayeb. 70 bare names are now
  aliases of their villages (`proposed`), so a bare name shared by several villages resolves to
  what they share unless the text names the district; two more for "يحمر الشقيف" and "يحمر
  البقاع". Left out, _chosen_: 35 bare forms that are ordinary words or mean something else in the
  press (حريق، راس، وادي، الجديدة، الحمرا…).
- **2026-10-28, from the whole year:** rule 8, the district or governorate a text names holds its
  places: a village named outside it is left out when another named village lies inside it ("محلة
  العين" near Andaqt, Akkar, is not Aain in Baalbek), and with "قضاء"/"محافظة" and no village
  inside, that unit is the answer; both are flagged. 17 aliases (`proposed`; "شدرا" left out: there
  is one in Akkar and one in Jezzine). 49 real place strings in the done test; 152 aliases, 111 of
  them `proposed`. Of the year's 208 fires, 33 are not on the map: highways, Beirut quarters, broad
  areas, and spellings still unknown ("طيردبا", "زوق مصبح", a rare hamza form "ٲ" the normaliser
  does not fold yet).

### Task 3 — Crawlers ✅ built 2026-10-22 (sources chosen from the census, §9)
- **Two machines, decided with the owner 2026-10-22.** GitHub's servers read the seven sources
  they can reach (Lebanon24, LBCI, Al Jadeed, MTV, Annahar, Tayyar, Lebanon Debate) three times a
  day (`crawl.yml`). **The owner's Mac** reads the four that block GitHub (NNA, Elnashra, Janoubia,
  L'Orient Today) three times a day and at log-in (`scripts/home-crawl.sh`, launchd). A Mac that
  was asleep or off catches up on its next run, back to 60 days (_chosen_). No purchase.
- Each run: discover → keyword filter (BRIEF §3) → fetch new candidates → save the text in the
  private store (`raw/<source>/<month>/`). An address is fetched once (`state/fetched/`); a failed
  fetch is retried next run. Files are split per source, so the two machines never collide.
- **NNA gives its lead paragraph only.** Its article text loads from `/api/`, which its robots.txt
  forbids; most NNA items are republished in full by the other outlets.
- **The Civil Defense daily bulletin** is parsed without a model (`crawler/bulletin.py`) into
  `data/official/daily_tallies.csv`: missions, fires and fires by type per day, each row checked
  (parts must add up; flagged, never corrected). Words not yet mapped land in `fires_other` and are
  listed by `crawler bulletins` (mapping: `data/official/mapping/civil_defense_bulletin.yaml`).
- Not built: the Civil Defense website itself (stale since September; its addresses return the
  listing), Lebanonfiles and Kataeb (bot check / browser-built).
- **Civil Defense data (owner, 2026-10-22):** the owner will try to obtain the bulletin archive
  directly; it enters through the official import path (task 8) when it arrives.
- **First month in the store (2026-10-22): 267 articles** from all eleven sources, and
  **12 bulletin days out of 30**. Only **one** of those days has the breakdown by fire type
  (19 Oct, from Lebanon24): NNA, which carries most bulletins, gives its first line only, and the
  other outlets rarely republish the full text. Getting the breakdown every day needs either the
  bulletin archive from Civil Defense or NNA (a data request), or NNA's full text — which loads
  from its robots-forbidden `/api/`, so we do not take it.

### Task 4 — Filter + extraction (started 2026-10-22)
- **What each article must yield (owner, 2026-10-22):** the type of location, the location, the
  type of hazard, the damage (deaths, injuries, buildings burned…) and the date. Location type and
  hazard each take **one primary tag and up to four more**; both lists must be mutually exclusive
  and exhaustive, built from what the NFPA/NFIRS use, and kept simple.
- **Lists v0.2 (`crawler/taxonomy.yaml`), after the owner's review 2026-10-23.** Four words kept
  apart: **site** (what kind of place burned: 15 categories, 63 sub-types — restaurants, shops
  with malls, and offices separated; light and heavy industry separated; industrial storage
  added), **location** (the map: the gazetteer of task 2), **hazard** (what started or fed it:
  15), **material** (what was burning: 14, each with its NFPA 10 fire class). Each list is
  closed by "not established". They replace the brief's `property_class` and `cause_reported`;
  `origin` (accidental / deliberate / conflict) stays separate. **Refined with the owner from
  real catches** — he will teach what to look for.
- **Materials: reported, never inferred.** A record carries the materials its article names. What
  a kind of site usually contains (`typical_materials`) is a separate lookup, shown labelled as
  typical and never counted as a finding (owner's question 2026-10-23; recommendation sent).
- **Extraction built (`crawler/extract.py`, `crawler/prompts/extract.md`):** Claude Haiku 5.5 with
  structured outputs held to a schema generated from the lists, so every tag is a listed id. A
  free first check sends only fire stories (fire words in the headline or opening): 78 of the
  first 289 articles. Runs on GitHub (`extract.yml`), where the key is; results go to the private
  store. Second pass (Claude Sonnet 5.5) not built yet.
- **First run (2026-10-23):** 78 articles, none refused or failed, 79 items, **22 fires in
  Lebanon**; the rest set aside as abroad, not a fire, or daily totals. My own read of the 22
  before the owner's review: three wrong (a general appeal against arson and a regrowth story
  taken as incidents; a UNIFIL vehicle fire given "electrical installation" — _corrected
  2026-10-23: I had also called "accidental" wrong because the headline asks "explosion or
  fault?", but the text answers it, a short circuit with no security incident_), one debatable (Tebnine: open burning or the
  battery as primary hazard), and one caused by the list itself ("سنتر", a commercial building,
  given as a mall cue). Review workbook: `private/review/2026-10-23-first-batch.xlsx`.
- **Owner's second review (2026-10-23)** and what changed — lists v0.3, instructions v3:
  - **War-related fires are out of scope but logged** (BRIEF amendment 9). Claude marks the origin
    `conflict_related`; code also counts as war-related any fire whose main hazard is munitions,
    or where munitions burned. A second check flags, for review, any other fire whose article
    uses war words (`filter_patterns.yaml`, `war`) or names munitions as a possible cause. Fireworks, celebratory gunfire and gas or battery
    explosions stay in scope (_chosen_).
  - **Three questions kept apart:** the **site** is the facility or place that witnessed the fire
    (14 categories, 58 sub-types), never the thing that burned; **what burned** is its own list
    (42 items in 12 groups, one main and up to four more); the **hazard** list splits fireworks
    (civil) from munitions (war). So vehicles moved to what burned, and the rubbish and vegetation
    site categories became waste sites and natural areas — the repetition the owner saw on row 13
    (a dump: site "rubbish", material "rubbish", typical "rubbish"). A facility the fire reached or
    was next to ("near a school") is now another site.
  - **Reported or deduced, everywhere** (`crawler/derive.py`): Claude records only what the article
    says; code adds, labelled, what such a site usually contains, what usually starts fires there,
    the origin a hazard implies (an electrical fault is accidental), the publication date when no
    fire date is given, and the district and governorate of a village.
  - A new record type `background` (an appeal, prevention, a fire long past) for the two first-run
    mistakes of that kind.
  - **Same fire, several articles → one row** (`crawler/dedupe.py`, brought forward from task 5).
  - **Bug found:** in draft 0.2, every label with a comma was cut at the comma (YAML's inline form),
    so the workbook showed "Plastics" for "Plastics, foam (sponge), rubber and tyres". Fixed; a test
    now fails on any stray key.
  - Results made with older instructions are classified again on the next run; `force` redoes all.
  - Trial of instructions v2 on 10 articles (2026-10-23): all answered, $0.0152 — about 12,200
    tokens in per article (the longer lists add ~3,000). It showed a burned vehicle left out of
    what burned; v3 says a vehicle that burned is always listed, and that a cause the article only
    asks about stays "not established".
- **Second run, instructions v3 (2026-10-23):** 79 articles, all answered, **$0.123**; 20 reports
  of fires in Lebanon → **13 fires** (9 in scope, 4 war-related) once duplicates merged. My read:
  the school now shows; the Saida dump's five articles are one fire; the war check flags the two
  unclear fires. Wrong: a sixth Saida article (the municipality's complaint) stayed apart because
  its place was given as "the garbage mountain" without the town, and a UNIFIL vehicle was left out
  of what burned. Instructions v4 take the town from a name ("بلدية صيدا"), add "other vehicle,
  type not stated", and a count of burned vehicles now implies a vehicle (deduced).
- **Third run, instructions v4 (2026-10-23):** 79 articles, all answered, **$0.124**; 21 reports
  → **13 fires** (9 in scope, 4 war-related). The six Saida dump articles are one fire; the UNIFIL
  vehicle and the Tebnine battery are now in what burned. Debatable, for the owner: the Nabatieh
  residents' appeal is one low-confidence "fire" (0.35, flagged); Borj Rahhal's burned land has no
  site type, the school is the other site. Workbook: `private/review/2026-10-23-second-batch.xlsx`,
  with a "Lists" sheet so the owner can correct or extend every entry.
- **Owner's third review (2026-10-27): keep it simple, nine questions.** The workbook now has one
  column per question — date, location, the site that witnessed the fire, what burned, the hazard,
  the origin, the damage, the gravity of the damage, the responders — 14 columns instead of 20.
  Each of site, what burned, hazard and origin is **one answer: reported if the article says it,
  else deduced (naming what it was deduced from), else "not established"**; deduced values are no
  longer shown beside reported ones. Deductions start from a reported main value only, never from
  another deduction: site ← what burned (wild vegetation → natural areas, crops → farmland); what
  burned ← the damage (a vehicle when vehicles burned), else the hazard (gas → gas cylinders),
  else the site; hazard ← what burned (cooking oil → cooking), else the site; origin ← the hazard.
  - **Gravity** is the brief's severity scale (§6), deduced from the damage: 4 deaths or several
    buildings, 3 injuries or displaced people, 2 damage without casualties, 1 no damage. Level 1
    reads "no damage (put out at its start)" where the brief said "extinguished on arrival", which
    articles rarely state. A new reported field, `property_damage` (none / damaged / not stated),
    carries damage stated in words ("اقتصرت الأضرار على الماديات") when there are no figures.
  - Responders moved into the lists, with Arabic cue words. Instructions v5.
- **Fourth run, instructions v5 (2026-10-27):** 108 articles for **$0.174** (two runs: the job's
  default cap of 100 applies when the limit is left empty — give a number), 27 reports → **17
  fires** (11 in scope, 6 war-related). Workbook: `private/review/2026-10-27-third-batch.xlsx`.
  Known gap: a place the map does not know ("منطقة الحوش") does not merge with a report that
  names it inside a longer place (two war-related reports of one fire) — _fixed 2026-10-27, task 5._
- **The owner's answers (2026-10-27).** The third workbook is right apart from what he had already
  pointed out (the one left: a fire listed twice, the al-Hawsh gap above). Order of work: the
  12-month history first, then the published data, then the site. Review by e-mail (task 5). The
  Civil Defense archive: he continues through his own contacts.
- **Classification runs on its own (2026-10-27).** It is a step of every crawl (`crawl.yml`, at
  most 60 articles a run, _chosen_: about 10 cents), and the owner's Mac starts that crawl as soon
  as it has saved new articles (`scripts/home-crawl.sh`, with his own GitHub login on the Mac). So
  NNA's Civil Defense bulletins are published minutes after the Mac reads them, not at GitHub's
  next scheduled run, which starts 3–7 hours late (§8). A call to Claude that failed (API or
  network error) is tried again on the next run; a refusal is kept for review.
- **Readers fixed (2026-10-27), before the 12-month history.** A count of what the generic reader
  had stored, by outlet: Lebanon24 **69 of 108** articles were the page menu (40 of them
  breaking-news flashes, which have no body at all); LBCI **30 of 39** flashes (a reading time and
  a copyright notice); MTV **24 of 37** began with a log-in box; Tayyar and Al Jadeed stored menus
  and a ticker of *other* headlines (which can mislead Claude, e.g. war words from another story);
  NNA cut its own summary in half on 4 pages ("<span s"). Each of those outlets is now read from
  its article block (`body` in `crawler/sources/`), and a page with no body is kept as its
  headline ("headline only", counted as "flash" in the crawl log). Janoubia, Lebanon Debate and
  L'Orient Today read correctly with the generic reader and keep it. _Added the same evening:_
  Annahar, whose pages carry a "most read" column of other stories (140 of 771 stored articles had
  it, found in the history check through false "war words" flags); its 771 articles were read again. The stored
  articles of the six outlets were read again, and those whose text changed are classified again.
- **Thin text (found 2026-10-23):** of the 20 reports, **17 gave Claude only a headline or one
  line**: NNA by design (its lead only, §8), and Lebanon24 and LBCI "breaking news" flashes, which
  have no body. That is why so much is "not established". About 11 regular Lebanon24 pages also
  stored the page menu instead of the article: a reader bug to fix (task 3 work).
- **Known issue, fixed 2026-10-27:** Lebanon24 serves one article under two addresses (sitemap and
  feed), so across runs the same story was stored twice; dedupe merges the two (same headline).
  Lebanon24's fetched list now records the article number, so a second address is not fetched.
- Keyword patterns in a UTF-8 YAML file, tested against labelled headlines.
- Extraction: Haiku 5.5 with structured output (`output_config.format`), one request per
  article; output is a **list** of items, each typed `incident` / `aggregate_report` / `not_a_fire`.
  Routine runs move to the Batch API (half price) once the instructions settle.
- The system prompt is identical for every request and is cached, cutting its input cost.
- Second pass on Sonnet 5.5 when confidence < 0.7 (_chosen in the brief_) or casualties are present.
- Names: the schema has no field that can hold one; a post-check also rejects any evidence quote
  that matches a name pattern and sends it to review.
- Golden set: 50 articles hand-labelled **by a person** (the owner or the reviewer), never by the
  model being tested. Precision, recall and F1 written to `data/quality/` (public) — the brief
  requires the figure on the methodology page whatever it is.

### Task 5 — Dedupe, geocode, review, publish
- **Dedupe v1 built early (2026-10-23, `crawler/dedupe.py`).** Two reports are the same fire when
  they come from different articles, their dates are at most **two days** apart (_chosen_: the
  brief's 36 hours is too tight when most articles give no fire date and dumps and forests burn for
  days), their places nest at district level or finer, and their sites agree. **Added 2026-10-27:**
  a place the gazetteer does not know at all matches a report whose place text names it ("منطقة
  الحوش" inside "منطقة الحوش بين برج الملوك وسهل مرجعيون"); a name it knows but cannot place ("the
  South", two governorates) is not enough. No alias was added for the places left off the map:
  al-Hawsh is the name of many places, Dahr el-Baidar sits on the Aley–Zahle boundary, and I do not
  know Wadi al-Khanazir's district for certain — a guess would put fires in the wrong district. A report joins a
  group only if it matches every report in it, so near-matches never chain two fires together.
  **Added 2026-10-28:** a factory whose product is not stated agrees with any factory the lists
  name "معمل …" (three fires of the year were counted twice: Beddawi, Hrayshe, Mkalles). Still
  counted twice, for the review: reports that name different towns for one fire (the Anfeh
  factory fire, called "the Chekka fire" by one article) or different sites (factory and warehouse).
  Conflicting counts or origins are flagged for review. Still to do: official values win on
  conflict (task 8), and a stable incident id.
- The published schema (`crawler/schema/incident.schema.json`) still has §6's `property_class` and
  `cause_reported`: to be aligned with the lists (site, what burned, hazard; reported and deduced
  apart) before anything is published.
- **Review: by e-mail (owner, 2026-10-27; BRIEF amendment 10).** Each new fire is e-mailed to one
  address the owner will give. This replaces the Google Sheet decided on 2026-10-10, and with it
  the Google service account. How the answer comes back is proposed, not decided: the reviewer
  replies "OK" or says what is wrong.
  - **Built 2026-10-27 (`crawler/notify.py`), switched off until the owner creates three secrets:**
    `MAIL_USERNAME` and `MAIL_PASSWORD` (a sending account and its app password) and `MAIL_TO` (the
    review address; a secret, so it never shows in this public repo or its logs). A step of every
    crawl. Every fire keeps a number (`state/fires.json`, F-1, F-2…) that the reply can quote; a
    number goes to one fire only (2026-10-28: when a new article split a fire, both parts had kept
    its number, and the second would never have been e-mailed). A fire is e-mailed once, when it is in scope and happened in the last 7 days (_chosen_): the
    12-month history goes to the reviewer as one workbook. War-related fires are not e-mailed.
    The e-mail is the workbook row: the nine answers, reported in bold, deduced with what they
    were deduced from. Draft approved by the owner: pending (sent 2026-10-27).
- Publish: parquet + csv + geojson + aggregate JSON files; `DATA_DICTIONARY.md` generated from the
  schema so the two cannot drift.
- Done test: a 14-day run, reviewed, with a recall figure against the owner's manual log.

### Task 6 — Tier 2 + backfill
Same adapters pointed at archives, month by month, resumable (state in the private store), so a
run that times out picks up where it stopped. Sanity plot of monthly counts.
**Scope (owner): the last 12 months (2026-10-22), then one more year (2026-10-29): two years.** The
10-year history is parked.
**Order (owner, 2026-10-27): the history before the published data and the site.**
- **Built 2026-10-27 (`crawler/backfill.py`).** Newest first, a week at a time for NNA (70 pages a
  week) and a month elsewhere, the daily crawl's keyword check,
  the outlet readers of task 3. Each crawl gives it a little time (GitHub 15 minutes, the Mac 20,
  _chosen_), shared between the sources, so the year fills in over a few days without anyone
  starting it; `backfill.yml` gives the GitHub sources a longer run by hand. It keeps its own
  lists (`state/backfill/`) and ends, per source, the day before the daily crawl's oldest article,
  so it never touches the daily crawl's files nor fetches the same article. A failed page is
  tried on the next two runs, then given up. The crawl's classification step picks up what it
  saves (at most 60 articles a run).
- **Archives read (2026-10-27):** NNA (daily sitemaps; lead only, as every day), Janoubia (its
  posts API), L'Orient Today (all article sitemaps, dated by last change) and Annahar (monthly
  sitemaps with headlines). **Not read, and why:** LBCI's archive sitemaps carry no dates and stop
  at July 2026; Lebanon24's stop in 2018; MTV's monthly sitemaps give numbers, not headlines (17,000
  addresses a month to open one by one); Al Jadeed and Tayyar have none; Lebanon Debate's pages
  stop going back; Elnashra has none (the Internet Archive lists some of its addresses — a later
  option). Most of their local news comes from NNA, which is read.
- **First runs (2026-10-27 evening):** Annahar, Janoubia and L'Orient Today complete for the 12
  months; NNA 22 weeks of 48 (newest first: back to late April). Found 2,400 articles in the store
  after the runs, of which 718 fire stories classified for **$1.19**; Annahar's 375 classified again
  after its reader was fixed (**$0.62**). Result so far: 296 reports → **192 fires (143 in scope, 49
  war-related)**, most from June to September — the months NNA has covered so far, and the
  season. My reading of a random sample of 15: the problems were the Annahar column (fixed) and
  the bare village names (fixed); one fire whose site looks wrong (trees beside a power line given
  "electricity network", low confidence, flagged).
- **Complete (2026-10-28 evening):** NNA's 48 weeks done on the Mac's evening run; every source's
  12 months read. 1,028 fire stories classified: **$1.71** for the results kept, **about $2.40** in
  all with the runs done again (Annahar's reader, older instructions). From 1 Nov 2025 to 28 Oct
  2026: 422 reports → **208 fires in scope** and 65 war-related (logged, not shown). The monthly
  counts (the sanity plot is the draft page's chart): November 2025 the most (49), then August 2026
  (35); 75% from June to November. NNA's reports run without a gap through September and October.
  Not yet reviewed by a person.
- **Second year (started 2026-10-29):** `backfill.DAYS` 365 → 730; each source carries on from
  where its first year stopped (only the oldest stretch, cut short before, is read again). The
  archives reach that far: NNA's daily sitemaps and Annahar's monthly ones answer for November 2024
  (checked 2026-10-29), Janoubia's reaches 2011, L'Orient Today's about 2018. The year holds the
  last weeks of the 2024 war (to the 27 November ceasefire): many fires from strikes, logged but
  not shown.

### Task 7 — Site v1
**Drafted first as a private page (owner, 2026-10-27):** an artifact or one self-contained HTML
file, reviewed by the owner, before anything is published or paid for (hosting, domain).
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

> **Superseded 2026-10-23.** Everything below this note was priced on Claude Haiku 4.5. The brief's
> model, Claude Haiku 5.5, costs $0.10 / $0.50 per million input / output tokens (prompts up to
> 100K tokens) — a tenth of Haiku 4.5. **Measured on the first run (2026-10-23): 78 articles for
> $0.0993, i.e. $0.0013 an article** (about 9,000 tokens in — mostly the instructions — and 740
> out). At about 80 fire articles a month that is **about 10 cents a month**; twelve months of
> history, _assuming the same density_, **about $1–2**. Caching the instructions and the Batch API
> would each cut it further; not worth the complexity yet. **Lists v0.3 (2026-10-23):** the longer
> lists bring it to about 11,800 tokens in and 770 out, **$0.0016 an article** (79 for $0.124).

Claude prices from the price list used on 2026-10-10: Haiku 4.5 at $1 / $5 per million input / output
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

**Revised 2026-10-22 with measured volumes.** Real Lebanese fire stories are rare (§9), but the
brief's keyword filter is deliberately broad ("explosion", "smoke", "generator"): from the GitHub
sources alone, **54 articles passed it in two days**. At ~$0.003 an article (Haiku 4.5 on the Batch
API, Sonnet 5 re-reading about one in four) that is **~$2–4 a month**. A stricter first check —
fire words plus a Lebanese place, both free — would cut it below $1. Ten years of history, one
time: **~$20–70** (_assumes today's density in past years; unknown_).

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
| 1b | ~~A machine in Lebanon~~ **done 2026-10-22**: the owner's own Mac, background job installed | task 3 | done |
| 2 | ~~8 or 9 governorates~~ **decided 2026-10-22: nine** (Keserwan-Jbeil separate) | task 5 | done |
| 3 | ~~Anthropic API key~~ **done 2026-10-22**: `ANTHROPIC_API_KEY` secret in place (the spend cap is set in Anthropic's console, not visible from here) | task 4 | done |
| 4 | A person to hand-label the 50-article golden set | task 4 | ~2–3 h, _estimated_ |
| 5 | ~~Google service account~~ **not needed (2026-10-27)**: review is by e-mail. Instead: the review address, and an account that sends the e-mails, as three secrets (`MAIL_USERNAME`, `MAIL_PASSWORD`, `MAIL_TO`) | task 5 | 15 min |
| 5b | How the reviewer answers each e-mail. Proposed: a reply "OK" or the correction, read from the sending account's inbox with the same app password | task 5 | a decision |
| 6 | ~~The reviewer~~ **decided 2026-10-27**: whoever reads the review address | task 5 | done |
| 7 | The manual Civil Defense Facebook log, kept for the same 14 days as the pilot run | task 5 | daily, minutes |
| 8 | Cloudflare account and the repo connected (root `site`, build `npm run build`, output `dist`) — only once the owner has approved the site's private draft (2026-10-27) | task 7 | 10 min |
| 9 | Disclosure/brand and the domain name | launch | a decision |
| 10 | A native speaker to review the Arabic and French interface text, and the `proposed` aliases | launch | ~1 h |
| 11 | GitHub account → Settings → Emails: keep the e-mail address private, so GitHub's own merges never write it into a commit | now | 1 min |

## 7. Worth knowing

- The US is replacing NFIRS with a new system, NERIS. NFIRS codes stay a sound, documented
  taxonomy for this purpose, but the methodology page should say which one we use and why.
  _Verify the NERIS rollout status before writing that page._

## 8. The sources, as found on 2026-10-22 (measured, from this machine, not from GitHub's)

Collected while finding real place strings for task 2. One look each: re-test from GitHub's
servers in task 3, because sites treat data-centre addresses differently.

| Source | Brief said | Found |
| --- | --- | --- |
| Elnashra (tier 1, "highest density") | server-rendered tag pages | **Bot check comes and goes** (blocked at 15:10, open at 16:30 the same day). The fire tag page is **stale** (newest item 14 Dec 2025); the security and miscellaneous sections are live, but older items load only in the browser, so a visit sees one to two days. We never get around a bot check. |
| Civil Defense website (tier 1, official) | per-incident statements by sequential ID | **Newest statement dated 30 Sep 2026** (22 days old). The article address in the brief returns the full listing page, not the statement; the listing's dates are unreliable. Needs real parsing work. |
| NNA (tier 1) | sitemaps + Playwright | **Works.** Daily sitemaps per category, headline in the address. Local news, 7 Sep–21 Oct: **1,641 headlines, about 8 individual fires**; the daily Civil Defense tally appears almost every day. |
| Lebanon24 (tier 1) | ~80 items/day RSS | Two feeds: 999 items over 35 days, **3 fire headlines**. |
| Lebanon Debate (tier 1) | listing pages | **Readable**: 24 dated articles a page, paging works. _Corrected the same day: a first check wrongly said "built in the browser" (wrong pattern)._ Its sitemap index is behind a bot check. |
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

## 9. Source census from GitHub's servers (2026-10-22) — and the daily bulletin

`census.yml`, one run, window 22 Sep – 21 Oct, 494 requests. Counts only here; the headlines
are in the private store (`census/2026-10-22/`). "Lebanese fires" is my reading of each headline,
not a measurement: most fire-word headlines were foreign (Hormuz tankers, France, Canada, Yemen).

| Source | From GitHub | Days its listing covers | Headlines | With fire words | Lebanese fires (read) |
| --- | --- | --- | --- | --- | --- |
| NNA | **bot check** | — | — | — | — |
| Elnashra | **bot check** | — | — | — | — |
| Janoubia | **bot check** | — | — | — | — |
| L'Orient Today | **bot check** | — | — | — | — |
| Lebanonfiles, Kataeb | articles built in the browser | — | — | — | — |
| Lebanon24, 3 RSS sections | ok | 30 | 1,218 | 6 + 1 daily bulletin | 2 |
| Lebanon24, news sitemap | ok | 2 | 671 | 6 | 1 |
| LBCI | ok | 6 | 905 | 9 | 1 |
| Al Jadeed | ok | 8 | 923 | 2 | 0 |
| Tayyar | ok | 4 | 420 | 1 | 0 |
| MTV | ok | 2 | 445 | 0 | 0 |
| Annahar | ok | 2 | 253 | 0 | 0 |
| Lebanon Debate | ok | 3 | 560 | 0 | 0 |

**Three findings.**
1. **GitHub's servers are blocked by four key sources**, NNA (the upstream of most items) among
   them; all four answered normally from a home connection in Lebanon the same day. One run
   only: bot checks come and go, so this needs repeating before it is treated as settled.
2. **Reported fires are rare.** Across every reachable source: three distinct Lebanese fires in a
   week (Hamat tunnel, a battery fire in Tebnine, a car fire in the South).
3. **Civil Defense publishes a daily fire count by type.** Its daily bulletin ("X missions in the
   past 24 hours", carried by NNA, republished in full by Lebanon24 — reachable from GitHub) lists
   fires put out, split by kind:

   | Bulletin | Fires | Electrical | Homes | Grass | Rubbish | Vehicles | Fruit trees |
   | --- | --- | --- | --- | --- | --- | --- | --- |
   | 19 Oct 2026 | 29 | 3 | 4 | 8 | 11 | 3 | — |
   | 12 Oct 2026 | 41 | 3 | 4 | 27 | 5 | 1 | 1 |

   Media reports name a handful of fires a week; the bulletin counts **29–41 a day** in these
   two samples. This is the national series the brief said did not exist, and it parses without a
   language model (fixed format). Not yet known: whether Lebanon24 republishes it every day, how
   far back it goes, and whether Beirut's own fire brigade (not Civil Defense) is included.

**Archive depth toward ten years** (owner, 2026-10-22: welcome). MTV's monthly sitemaps reach
2016 (8,881 addresses for October 2016) but carry no headlines; Annahar's reach 2019 with
headlines (33 addresses in Oct 2019, 4,613 in Oct 2022); the Internet Archive holds at least
2,000 Elnashra article addresses from 2016, headline in each address. From a home connection:
Janoubia's archive reaches 2011, L'Orient Today's about 2018, NNA's daily sitemaps about two years.
