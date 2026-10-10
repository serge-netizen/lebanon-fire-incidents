"""Command-line entry point: `uv run crawler ...`."""

from __future__ import annotations

import argparse
import json
import os
import sys

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
    print(f"private dir {'present' if config.PRIVATE_DIR.is_dir() else 'absent'}  {config.PRIVATE_DIR}")
    print(f"api key     {'set' if os.environ.get('ANTHROPIC_API_KEY') else 'not set'}")
    print(f"models      extract={config.EXTRACT_MODEL}  second_pass={config.SECOND_PASS_MODEL}")
    print("dry run complete: nothing fetched, nothing written")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="crawler", description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="check wiring only; no network, no writes")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("run", help="one scheduled crawl: discover → … → publish")
    sub.add_parser("backfill", help="crawl archives (task 6)")
    args = parser.parse_args(argv)

    if args.dry_run:
        return dry_run()
    if args.command is None:
        parser.print_help()
        return 0
    print(f"'{args.command}' is not built yet — see docs/BUILD_PLAN.md", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
