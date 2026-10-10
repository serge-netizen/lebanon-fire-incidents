"""Registry of outlet adapters. Tier 1 arrives in task 3, Tier 2 in task 6."""

from __future__ import annotations

from crawler.sources.base import Source

SOURCES: dict[str, type[Source]] = {}
