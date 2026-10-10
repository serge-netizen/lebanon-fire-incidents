# Lebanon Fire Incidents

A public, trilingual (Arabic / English / French) record of fire incidents in Lebanon,
compiled from news reports and official press statements, categorised with the US NFIRS
taxonomy, and published as open data with a transparent methodology.

**Status:** scaffold. No data is published yet. See `docs/BUILD_PLAN.md`.

## Layout

| Path | What it is |
| --- | --- |
| `crawler/` | Python 3.12 pipeline (uv): discover → filter → fetch → extract → dedupe → geocode → review → publish |
| `crawler/schema/incident.schema.json` | The one definition of an incident record |
| `data/published/` | Open data (CC BY 4.0) and aggregates the site reads |
| `data/gazetteer/` | Offline place-name resolution |
| `data/official/` | Mappings for official series |
| `site/` | Astro static site, served by Cloudflare Pages |
| `private/` | **Not in this repo.** Raw article text and run state live in a separate private repo |

## Run it

```bash
uv sync
uv run pytest
uv run crawler --dry-run
cd site && npm ci && npm run build
```

## Licences

Code: MIT. Data: CC BY 4.0 (see `data/LICENSE.md`).
