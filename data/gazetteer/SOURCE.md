# Gazetteer sources

## `lebanon.parquet` — generated, never edited by hand
Rebuild with `uv sync --extra gazetteer && uv run crawler gazetteer`.

| | |
| --- | --- |
| Dataset | Lebanon – Subnational Administrative Boundaries (COD-AB), HDX id `cod-ab-lbn` |
| Publisher | OCHA Field Information Services; source: Council for Development and Reconstruction (CDR) |
| Licence | **CC BY-IGO** (checked 2026-10-22). Attribution required. |
| File used | `lbn_admin_boundaries.xlsx` (tables only: names, P-codes, centre points; no shapes) |
| Version | v02, valid on 2024-11-13; boundaries created 2014-05-02 |
| SHA-256 of the file used | `02d9bdbc54963bff92c813cd200e15fcdbb3e5436f98a4dc7d5b8be1c4855aba` |
| Downloaded | 2026-10-22 |

Attribution text for the site: *Administrative boundaries: Council for Development and
Reconstruction (CDR) / OCHA, via the Humanitarian Data Exchange, CC BY-IGO.*

### What the table contains
- 8 governorates, 26 districts (cazas) and 1,610 units at the third level: **1,545 cadastral
  areas** plus **65 "Litige" (disputed) strips** between them. Every unit has an English name, a
  P-code and the centre point OCHA publishes; every cadastral area also has an Arabic name. A
  centre point is a reference position, not a measured location.
- The 65 disputed strips are kept, flagged `is_place = false`, and never matched by name.
- 17 areas OCHA labels "Conflict", with no name and no P-code: dropped.

### Known limits of the source
- **Eight governorates, not nine.** The table predates the Keserwan-Jbeil governorate (2017); it
  keeps Kesrouan and Jbeil inside Mount Lebanon. Whether the site shows 8 or 9 is an open decision.
- Governorate P-codes follow the post-2014 structure, district P-codes the older one (OCHA's own
  caveat): never derive a parent from a P-code's digits — read `adm1_pcode` / `adm2_pcode`.
- Cadastral-area P-codes are plain numbers, unique within Lebanon only; a record's `country`
  field makes them unique across countries.
- OCHA's Arabic names drop the article inconsistently (بترون, صرفند, نبطية الفوقا) and give a
  bare city name to one of a city's several areas (صيدا, جونيه, زحلة). The resolver handles both.

## `aliases.csv` — hand-maintained
Other spellings and names. `status` is `verified` (a standard name or spelling) or `proposed`
(rests on general knowledge; a reviewer should confirm). `level` `region` maps one word to
several units, resolved to what they share.

## `common_words.csv` — hand-maintained
Place names that are also ordinary words. `cue`: matches only after بلدة/منطقة/حي…;
`article`: never matches when written with "ال"; `needs_article`: only matches with "ال".
Rows marked "found in headlines" came from running the resolver over 998 Lebanon24 headlines
on 2026-10-22 and reading every match.
