"""The private store on disk (docs/BUILD_PLAN.md §2): article text, what has been fetched, and
when each source last ran. On GitHub and on the owner's Mac it is a clone of the private repo at
./private. Files are split per source, so the two machines never write the same file."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from collections.abc import Iterator
from pathlib import Path

from crawler import config
from crawler.sources.base import FetchedArticle
from crawler.sources.common import BEIRUT


class Store:
    def __init__(self, root: Path | None = None):
        self.root = root or config.PRIVATE_DIR
        self._fetched: dict[str, set[str]] = {}

    # ---- which addresses already have their text saved
    def _fetched_path(self, slug: str) -> Path:
        return self.root / "state" / "fetched" / f"{slug}.txt"

    def fetched(self, slug: str) -> set[str]:
        if slug not in self._fetched:
            p = self._fetched_path(slug)
            self._fetched[slug] = set(p.read_text(encoding="utf-8").splitlines()) if p.exists() else set()
        return self._fetched[slug]

    def mark_fetched(self, slug: str, url: str) -> None:
        if url in self.fetched(slug):
            return
        p = self._fetched_path(slug)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(url + "\n")
        self._fetched[slug].add(url)

    # ---- when a source last ran without error
    def _runs_path(self, slug: str) -> Path:
        return self.root / "state" / "runs" / f"{slug}.json"

    def last_success(self, slug: str) -> dt.datetime | None:
        p = self._runs_path(slug)
        if not p.exists():
            return None
        stamp = json.loads(p.read_text(encoding="utf-8")).get("last_success")
        return dt.datetime.fromisoformat(stamp) if stamp else None

    def resume_from(self, slug: str) -> dt.date | None:
        """Oldest day still waiting to be fetched, when a run hit its fetch limit."""
        p = self._runs_path(slug)
        stamp = json.loads(p.read_text(encoding="utf-8")).get("resume_from") if p.exists() else None
        return dt.date.fromisoformat(stamp) if stamp else None

    def record_run(self, slug: str, report: dict, success: bool, resume_from: dt.date | None = None) -> None:
        p = self._runs_path(slug)
        p.parent.mkdir(parents=True, exist_ok=True)
        previous = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
        now = dt.datetime.now(BEIRUT).isoformat(timespec="seconds")
        data = {"last_success": now if success else previous.get("last_success"), "last_attempt": now,
                "resume_from": resume_from.isoformat() if resume_from else (None if success else previous.get("resume_from")),
                "last_report": report}
        p.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    # ---- article text
    def save(self, article: FetchedArticle) -> Path:
        key = hashlib.sha1(article.url.encode()).hexdigest()[:16]
        month = (article.published_at or article.fetched_at).strftime("%Y-%m")
        path = self.root / "raw" / article.outlet / month / f"{key}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {k: (v.isoformat() if isinstance(v, dt.datetime) else v) for k, v in article.__dict__.items()}
        path.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
        return path

    def articles(self) -> Iterator[dict]:
        for path in sorted((self.root / "raw").glob("*/*/*.json")):
            record = json.loads(path.read_text(encoding="utf-8"))
            record["raw_ref"] = str(path.relative_to(self.root))
            yield record
