"""Registry of outlet adapters (task 3). `where` says which machine can read each one."""

from __future__ import annotations

from crawler.sources.base import Source
from crawler.sources.listings import NNA, Elnashra, Janoubia, LebanonDebate, LOrientToday
from crawler.sources.sitemaps import LBCI, MTV, AlJadeed, Annahar, Lebanon24, Tayyar

SOURCES: dict[str, type[Source]] = {s.slug: s for s in (
    Lebanon24, LBCI, AlJadeed, MTV, Annahar, Tayyar, LebanonDebate,  # GitHub's servers
    NNA, Elnashra, Janoubia, LOrientToday,                            # a Lebanese connection only
)}


def sources_for(where: str) -> list[Source]:
    return [cls() for cls in SOURCES.values() if where == "all" or cls.where == where]
