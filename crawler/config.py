"""Paths, models and crawl etiquette in one place.

Nothing here is a secret. Keys (ANTHROPIC_API_KEY, the private-repo token, the
review-sheet service account) arrive only as environment variables in CI.
"""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT / "crawler" / "schema" / "incident.schema.json"
PROMPTS_DIR = REPO_ROOT / "crawler" / "prompts"

# Public, committed to this repo.
DATA_DIR = REPO_ROOT / "data"
PUBLISHED_DIR = DATA_DIR / "published"
GAZETTEER_DIR = DATA_DIR / "gazetteer"
OFFICIAL_DIR = DATA_DIR / "official"

# Private: raw article text, run state, rejected items, official files as received.
# Gitignored here. In CI it is a checkout of the private data repo (docs/BUILD_PLAN.md §2).
PRIVATE_DIR = Path(os.environ.get("FIRE_PRIVATE_DIR", REPO_ROOT / "private")).resolve()
RAW_DIR = PRIVATE_DIR / "raw"
STATE_DIR = PRIVATE_DIR / "state"
REJECTED_DIR = PRIVATE_DIR / "rejected"
PRIVATE_OFFICIAL_DIR = PRIVATE_DIR / "official"

# Models (BRIEF §4.4, as amended). Batch API halves the price of both.
EXTRACT_MODEL = "claude-haiku-4-5"
SECOND_PASS_MODEL = "claude-sonnet-5"
SECOND_PASS_BELOW_CONFIDENCE = 0.7  # Chosen in the brief, not measured. Revisit after the golden set (task 4).

# Crawl etiquette (BRIEF §3).
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
)
REQUESTS_PER_SECOND_PER_HOST = 1.0
TIMEZONE = "Asia/Beirut"
