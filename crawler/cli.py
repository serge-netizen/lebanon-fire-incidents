"""Command-line entry point: `uv run crawler ...`."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

from crawler import config
from crawler.sources import SOURCES


def load_schema() -> dict:
    with config.SCHEMA_PATH.open(encoding="utf-8") as f:
        schema = json.load(f)
    Draft202012Validator.check_schema(schema)
    return schema


def dry_run() -> int:
    """Check the pipeline is wired up without touching the network or spending money."""
    schema = load_schema()
    print(f"schema      ok  {config.SCHEMA_PATH.relative_to(config.REPO_ROOT)} v{schema['properties']['schema_version']['const']}")
    print(f"adapters    {len(SOURCES)} registered: {', '.join(sorted(SOURCES)) or '(none yet — task 3)'}")
    from crawler.geocode import gazetteer

    g = gazetteer()
    levels = [u.level for u in g.by_pcode.values() if u.is_place]
    print(f"gazetteer   {levels.count(1)} governorates, {levels.count(2)} districts, "
          f"{levels.count(3)} cadastral areas, {len(g.index)} searchable names")
    print(f"private dir {'present' if config.PRIVATE_DIR.is_dir() else 'absent'}  {config.PRIVATE_DIR}")
    print(f"api key     {'set' if os.environ.get('ANTHROPIC_API_KEY') else 'not set'}")
    print(f"models      extract={config.EXTRACT_MODEL}  second_pass={config.SECOND_PASS_MODEL}")
    print("dry run complete: nothing fetched, nothing written")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="crawler", description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="check wiring only; no network, no writes")
    sub = parser.add_subparsers(dest="command")
    crawl = sub.add_parser("run", help="one crawl: discover, filter, fetch, save to the private store")
    crawl.add_argument("--where", choices=["github", "home", "all"], required=True,
                       help="github: sources GitHub's servers can read; home: those needing a Lebanese connection")
    crawl.add_argument("--days", type=int, default=3)
    crawl.add_argument("--max-fetch", type=int, default=150, help="per source, per run")
    sub.add_parser("bulletins", help="rebuild data/official/daily_tallies.csv from the private store")
    ext = sub.add_parser("extract", help="Claude classifies the fire articles in the private store (task 4)")
    ext.add_argument("--limit", type=int, default=None, help="at most this many articles")
    ext.add_argument("--force", action="store_true", help="re-read articles already classified")
    ext.add_argument("--workers", type=int, default=4)
    rev = sub.add_parser("review", help="write the owner's review workbook from the classifications")
    rev.add_argument("--out", type=Path, required=True)
    sub.add_parser("backfill", help="crawl archives (task 6)")
    gaz = sub.add_parser("gazetteer", help="rebuild the place-name table from OCHA's spreadsheet")
    gaz.add_argument("--xlsx", type=Path, help="use a local copy instead of downloading")
    geo = sub.add_parser("geocode", help="resolve a place string, e.g. 'بلدة تول - قضاء النبطية'")
    geo.add_argument("text")
    cen = sub.add_parser("census", help="count fire headlines per source over recent days (task 3)")
    cen.add_argument("--days", type=int, default=30)
    cen.add_argument("--out", type=Path, default=None, help="default: <private store>/census")
    args = parser.parse_args(argv)

    if args.dry_run:
        return dry_run()
    if args.command is None:
        parser.print_help()
        return 0
    if args.command == "gazetteer":
        from crawler.gazetteer import build

        print(json.dumps(build(args.xlsx), indent=2))
        return 0
    if args.command == "run":
        from crawler import pipeline

        reports = pipeline.run(args.where, days=args.days, max_fetch=args.max_fetch)
        pipeline.print_reports(reports)
        return 0
    if args.command == "bulletins":
        from crawler import bulletin
        from crawler.store import Store

        found = bulletin.from_store(Store().articles())
        bulletin.write_csv(found)
        checks = {}
        for b in found:
            checks[b.check] = checks.get(b.check, 0) + 1
        unmapped = sorted({u for b in found for u in b.unmapped})
        print(f"bulletins: {len(found)} days, checks {checks}, unmapped fire types: {unmapped or 'none'}")
        return 0
    if args.command == "extract":
        from crawler import extract

        totals = extract.run(limit=args.limit, force=args.force, workers=args.workers)
        print(json.dumps(totals, indent=1))  # counts and cost only: job logs are public
        return 0
    if args.command == "review":
        from crawler import review

        print(json.dumps(review.write(args.out), indent=1))
        return 0
    if args.command == "census":
        from crawler import census

        summary = census.run(args.days, args.out or config.PRIVATE_DIR / "census")
        census.print_table(summary)  # counts only: job logs are public
        return 0
    if args.command == "geocode":
        from crawler.geocode import resolve

        print(json.dumps(resolve(args.text).as_dict(), ensure_ascii=False, indent=2))
        return 0
    print(f"'{args.command}' is not built yet — see docs/BUILD_PLAN.md", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
