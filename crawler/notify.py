"""One e-mail per new fire to the review address (owner, 2026-10-27; BRIEF amendment 10).

Every fire keeps a number (state/fires.json maps each report — an article and its place in it —
to its fire's number; a fire made of reports already numbered takes the smallest). A number goes
to one fire only: when a new article splits a numbered fire in two, the number stays with the
part that has most of its reports (the older part on a tie) and the other part takes a new one
(2026-10-28: both parts kept it, and the second would never have been e-mailed). A fire is
e-mailed once, when it is in scope (war-related fires are logged, not shown, not e-mailed) and
happened in the last week: the history goes to the reviewer as a workbook, not as
hundreds of e-mails. The e-mail answers the nine questions as the review workbook does
(review.fire_row), lists the articles, and asks for a reply.

Sending needs three secrets the owner creates: MAIL_USERNAME and MAIL_PASSWORD (the sending
account and its app password) and MAIL_TO (the review address). Without them nothing is sent and
nothing is marked sent, so the last week's fires go out on the first run that has them. Only
counts are printed: GitHub job logs are public.
"""

from __future__ import annotations

import datetime as dt
import html
import json
import os
import smtplib
from collections import Counter
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path

from crawler.dedupe import Incident, incidents, load
from crawler.derive import IN_SCOPE
from crawler.review import FIRE_COLUMNS, NOT_ESTABLISHED, fire_row
from crawler.sources.common import BEIRUT
from crawler.store import Store

RECENT_DAYS = 7  # chosen: older fires are history, reviewed in a workbook
SENDER_NAME = "Lebanon fire incidents"
QUESTIONS = ["Date", "Location", "Site that witnessed the fire", "What burned", "Hazard", "Origin", "Damage",
             "Gravity of the damage", "Responders"]
SHORT = {"Site that witnessed the fire": "Site", "Gravity of the damage": "Gravity"}
TITLES = [t for t, _ in FIRE_COLUMNS]


# ---------------------------------------------------------------- numbers

def number(registry: dict, fires: list[Incident]) -> list[int]:
    """Each fire's number, oldest fire first for new numbers; `registry` is updated in place."""
    registry.setdefault("next", 1)
    reports = registry.setdefault("reports", {})
    order = sorted(range(len(fires)), key=lambda n: (fires[n].date, fires[n].reports[0].url))
    held = {n: Counter(reports[r.key] for r in fires[n].reports if r.key in reports) for n in order}
    winner: dict[int, int] = {}  # number → the fire with most of its reports, the older on a tie
    for n in order:
        for k, count in held[n].items():
            if k not in winner or count > held[winner[k]][k]:
                winner[k] = n
    out: dict[int, int] = {}
    for k in sorted(winner):  # a fire that wins several numbers takes the smallest
        out.setdefault(winner[k], k)
    for n in order:
        if n not in out:
            out[n], registry["next"] = registry["next"], registry["next"] + 1
        for r in fires[n].reports:
            reports[r.key] = out[n]
    return [out[n] for n in range(len(fires))]


# ---------------------------------------------------------------- the e-mail

def _esc(text: str) -> str:
    return html.escape(text, quote=True)


def _answer(cell: str) -> str:
    """A reported value in bold; a deduced one plain, its note in amber; 'not established' grey."""
    lines = [x for x in str(cell).split("\n") if x]
    if not lines or lines[0] in (NOT_ESTABLISHED, "not stated"):
        return f'<span style="color:#9ca3af">{_esc(lines[0] if lines else "not stated")}</span>'
    deduced = any(x.startswith("— deduced") for x in lines)
    out = []
    for line in lines:
        if line.startswith("— deduced"):
            out.append(f'<div style="font-size:12px;color:#92400e;margin-top:2px">{_esc(line)}</div>')
        elif line.startswith("— ") or line.endswith("— reported"):
            out.append(f'<div style="font-size:12px;color:#6b7280;margin-top:2px">{_esc(line)}</div>')
        elif line.startswith("as written: "):
            out.append(f'<div style="font-size:12px;color:#6b7280;margin-top:2px">as written: <span dir="rtl" '
                       f'lang="ar">{_esc(line.removeprefix("as written: "))}</span></div>')
        else:
            weight = "color:#374151" if deduced else "font-weight:600;color:#111827"
            out.append(f'<div style="{weight}">{_esc(line)}</div>')
    return "".join(out)


def render(n: int, fire: Incident) -> tuple[str, str, str]:
    """(subject, plain text, HTML) of the e-mail for fire number `n`."""
    row = dict(zip(TITLES, fire_row(n, fire), strict=True))
    summary = row[TITLES[3]][0].rsplit("\n[", 1)[0]
    place = row["Location"].split("\n")[0]
    site = row["Site that witnessed the fire"].split("\n")[0].split(" (also")[0]
    site = "Fire" if site == NOT_ESTABLISHED else site
    town = place.split(" · ")[0]
    date = fire.date.strftime("%-d %b %Y")
    subject = f"New fire F-{n}: " + (f"{site}, {town}" if site != "Fire" else town) + f" — {date}"
    reply = ('Reply OK if all of this is right, or write what is wrong, one line per question '
             '(e.g. "Site: restaurant", "Not a fire", "Same fire as F-12"). Nothing is published before your OK.')
    text = "\n".join([subject, "", summary, "", *(f"{q}: {' '.join(str(row[q]).split(chr(10)))}" for q in QUESTIONS),
                      *([f"To check: {row['Checks'].replace(chr(10), '; ')}"] if row["Checks"] else []), "",
                      "Articles:", *(f"- {r.outlet}, {r.published:%-d %b}: {r.headline}\n  {r.url}" for r in fire.reports),
                      "", reply])
    rows = "".join(
        f'<tr><td style="padding:10px 12px;border-top:1px solid #e5e7eb;color:#4b5563;font-size:13px;width:34%;'
        f'vertical-align:top">{_esc(SHORT.get(q, q))}</td><td style="padding:10px 12px;border-top:1px solid #e5e7eb;'
        f'font-size:14px;vertical-align:top">{_answer(row[q])}</td></tr>' for q in QUESTIONS)
    checks = (f'<div style="margin:16px 0 0;padding:10px 12px;background:#fff7e6;border:1px solid #f3d19c;'
              f'border-radius:8px;font-size:13px;color:#7a4b00"><b>To check:</b> '
              f'{_esc(row["Checks"].replace(chr(10), "; "))}</div>') if row["Checks"] else ""
    articles = "".join(
        f'<li style="margin:0 0 8px"><span style="color:#4b5563;font-size:12px">{_esc(r.outlet)} · {r.published:%-d %b}'
        f'</span><br><a href="{_esc(r.url)}" style="color:#1d4ed8;text-decoration:none" dir="rtl" lang="ar">'
        f'{_esc(r.headline)}</a></li>' for r in fire.reports)
    body = f'''<div style="max-width:620px;margin:0 auto;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif">
<div style="font-size:12px;letter-spacing:.04em;text-transform:uppercase;color:#6b7280">New fire · F-{n}</div>
<div style="font-size:20px;font-weight:700;color:#111827;margin:4px 0 10px">{_esc(site)} — {_esc(place)}</div>
<p style="margin:0 0 14px;font-size:15px;line-height:1.5;color:#1f2937">{_esc(summary)}</p>
<table role="presentation" style="width:100%;border-collapse:collapse;border:1px solid #e5e7eb">{rows}</table>{checks}
<div style="margin:18px 0 6px;font-size:13px;font-weight:700;color:#374151">Articles ({len(fire.reports)})</div>
<ul style="margin:0;padding:0 0 0 18px;font-size:14px;line-height:1.5">{articles}</ul>
<div style="margin:18px 0 8px;padding:12px;background:#eef6ff;border:1px solid #c7ddfb;border-radius:8px;font-size:14px;line-height:1.5;color:#1e3a5f">{_esc(reply)}</div>
<div style="font-size:12px;color:#9ca3af;margin:12px 0">Bold: the article says it (reported). Amber note: deduced from something the article does say, which it names. Grey: neither.</div>
</div>'''
    return subject, text, body


# ---------------------------------------------------------------- a run

def _settings() -> dict | None:
    s = {k: os.environ.get(k, "") for k in ("MAIL_USERNAME", "MAIL_PASSWORD", "MAIL_TO")}
    if not all(s.values()):
        return None
    return s | {"MAIL_SERVER": os.environ.get("MAIL_SERVER") or "smtp.gmail.com"}


def send(settings: dict, due: list[tuple[int, Incident]], sent_path: Path) -> None:
    """Each e-mail is marked sent as soon as it has gone, so a failure part-way repeats none."""
    sent_path.parent.mkdir(parents=True, exist_ok=True)
    with smtplib.SMTP_SSL(settings["MAIL_SERVER"], 465, timeout=60) as smtp, sent_path.open("a", encoding="utf-8") as fh:
        smtp.login(settings["MAIL_USERNAME"], settings["MAIL_PASSWORD"])
        for n, fire in due:
            subject, text, body = render(n, fire)
            msg = EmailMessage()
            msg["Subject"], msg["To"] = subject, settings["MAIL_TO"]
            msg["From"] = formataddr((SENDER_NAME, settings["MAIL_USERNAME"]))
            msg.set_content(text)
            msg.add_alternative(f"<!doctype html><html><body>{body}</body></html>", subtype="html")
            smtp.send_message(msg)
            fh.write(f"F-{n}\n")
            fh.flush()


def run(store: Store | None = None, today: dt.date | None = None) -> dict:
    store = store or Store()
    today = today or dt.datetime.now(BEIRUT).date()
    fires = incidents(load(store).reports)
    registry_path, sent_path = store.root / "state" / "fires.json", store.root / "state" / "notified.txt"
    registry = json.loads(registry_path.read_text(encoding="utf-8")) if registry_path.exists() else {}
    numbers = number(registry, fires)
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(json.dumps(registry, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    sent = set(sent_path.read_text(encoding="utf-8").split()) if sent_path.exists() else set()
    due = [(n, f) for n, f in zip(numbers, fires, strict=True)
           if f.scope == IN_SCOPE and (today - f.date).days < RECENT_DAYS and f"F-{n}" not in sent]
    settings = _settings()
    if settings and due:
        send(settings, due, sent_path)
    return {"fires": len(fires), "due": len(due), "sent": len(due) if settings else 0,
            "mail": "configured" if settings else "not configured: nothing sent"}
