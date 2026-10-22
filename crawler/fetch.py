"""Polite fetching (BRIEF §3): robots.txt honoured, one request per second per host, no stale
caches, and a bot check reported as such — never worked around."""

from __future__ import annotations

import gzip
import re
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

from crawler import config

# Text that marks an anti-bot interstitial rather than the page asked for.
BOT_CHECK_MARKERS = ("Just a moment...", "cf-chl", "challenge-platform", "Attention Required!",
                     "Enable JavaScript and cookies to continue")


@dataclass
class Page:
    url: str
    status: int | None      # None when no request was sent
    body: bytes
    blocked: str | None = None  # "robots" | "bot_check" | "error: <kind>"

    @property
    def ok(self) -> bool:
        return self.blocked is None and self.status == 200

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")


class PoliteClient:
    def __init__(self, per_host_interval: float | None = None, timeout: float = 40):
        self._http = httpx.Client(
            headers={"User-Agent": config.USER_AGENT, "Cache-Control": "no-cache",
                     "Accept-Language": "ar,en;q=0.8,fr;q=0.6"},
            timeout=timeout, follow_redirects=True,
        )
        self._interval = per_host_interval if per_host_interval is not None else 1 / config.REQUESTS_PER_SECOND_PER_HOST
        self._last: dict[str, float] = {}
        self._robots: dict[str, list[tuple[str, bool]]] = {}
        self.requests = 0

    def get(self, url: str) -> Page:
        if not self.allowed(url):
            return Page(url, None, b"", blocked="robots")
        page = self._send(url)
        if page.status in (429, 500, 502, 503, 504) and page.blocked is None:
            time.sleep(5)
            page = self._send(url)
        return page

    def allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        root = f"{parts.scheme}://{parts.netloc}"
        if root not in self._robots:
            page = self._send(root + "/robots.txt")
            readable = page.ok and b"<html" not in page.body[:500].lower()
            # No readable robots.txt means nothing is disallowed (RFC 9309 §2.3.1.3).
            self._robots[root] = parse_robots(page.text) if readable else []
        path = parts.path or "/"
        return robots_allows(self._robots[root], path + (f"?{parts.query}" if parts.query else ""))

    def _send(self, url: str) -> Page:
        host = urlsplit(url).netloc
        wait = self._last.get(host, 0.0) + self._interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last[host] = time.monotonic()
        self.requests += 1
        try:
            r = self._http.get(url)
        except httpx.HTTPError as e:
            return Page(url, None, b"", blocked=f"error: {type(e).__name__}")
        body = r.content
        if body[:2] == b"\x1f\x8b":  # gzipped sitemap served as a plain file
            body = gzip.decompress(body)
        head = body[:20000].decode("utf-8", errors="replace")
        if r.status_code in (403, 503) and any(m in head for m in BOT_CHECK_MARKERS):
            return Page(url, r.status_code, body, blocked="bot_check")
        return Page(url, r.status_code, body)


def parse_robots(text: str) -> list[tuple[str, bool]]:
    """The (path pattern, allowed) rules of the group for all crawlers, "User-agent: *".

    Our requests carry a browser user-agent, so no bot-specific group applies to them.
    """
    groups: list[tuple[list[str], list[tuple[str, bool]]]] = []
    agents: list[str] = []
    rules: list[tuple[str, bool]] = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        field, value = (x.strip() for x in line.split(":", 1))
        field = field.lower()
        if field == "user-agent":
            if rules:  # a user-agent line after rules starts a new group
                groups.append((agents, rules))
                agents, rules = [], []
            agents.append(value.lower())
        elif field in ("allow", "disallow") and agents and value:
            rules.append((value, field == "allow"))
    if agents:
        groups.append((agents, rules))
    return [rule for names, rs in groups if "*" in names for rule in rs]


def robots_allows(rules: list[tuple[str, bool]], path: str) -> bool:
    """RFC 9309: the longest matching rule wins; on a tie, Allow wins; no match means allowed.
    (Python's urllib.robotparser lets the first rule win instead, which is wrong for files like
    NNA's: "Allow: /" followed by "Disallow: /api/".)"""
    best: tuple[int, bool] | None = None
    for pattern, allow in rules:
        regex = re.escape(pattern).replace(r"\*", ".*")
        if regex.endswith(r"\$"):
            regex = regex[:-2] + "$"
        if re.match(regex, path):
            key = (len(pattern), allow)
            if best is None or key > best:
                best = key
    return True if best is None else best[1]
