"""The reviewer's replies to the fire e-mails (owner's choice, 2026-10-29).

A reply says "OK", or gives one line per wrong answer: the question, the right answer and why
("Site: warehouse because the article says depot"). "Not a fire" and "Same fire as F-12" judge
the whole fire. Each reply is kept in the private store (state/reviews.jsonl) next to what the
e-mail showed (state/emailed/F-n.json), so it is a labelled example: what Claude answered, what
the reviewer answered, and why. The owner means to train an agent on them. A line that is none
of these is kept as a note for a person to read; nothing is guessed. Every reply is answered with
what was recorded, so a misread line is caught.

Only replies that really come from the review address are read: the sender is that address, or
another one on its domain when the domain is the reviewer's own (not a shared provider such as
gmail.com), and the receiving server's own check of the mail passed for that domain. The address
comes from the MAIL_TO secret and is never written here or in a log. Corrections are not applied
to anything yet: publishing (task 5) will read them.
"""

from __future__ import annotations

import datetime as dt
import html
import imaplib
import json
import os
import re
import smtplib
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import formataddr, parseaddr, parsedate_to_datetime

from crawler.notify import QUESTIONS, SENDER_NAME, SHORT, _settings
from crawler.sources.common import BEIRUT
from crawler.store import Store

WINDOW_DAYS = 30  # chosen: each run looks at the last month's mail again; a reply already kept is skipped
SHARED_DOMAINS = frozenset({  # chosen: anyone can open an address there, so only the review address itself counts
    "gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "live.com", "msn.com", "icloud.com", "me.com",
    "mac.com", "yahoo.com", "ymail.com", "aol.com", "proton.me", "protonmail.com", "gmx.com", "gmx.net",
    "mail.com", "yandex.com", "zoho.com",
})
NAMES = {q.lower(): q for q in QUESTIONS} | {s.lower(): q for q, s in SHORT.items()} | {
    "place": "Location", "when": "Date", "burned": "What burned", "material": "What burned", "cause": "Origin",
    "severity": "Gravity of the damage", "responder": "Responders",
}
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
EXAMPLE = '"Site: warehouse because the article says depot"'


# ---------------------------------------------------------------- what a reply says

_OK = {"ok", "okay", "ok thanks", "ok thank you", "all ok", "all good", "all correct", "correct", "looks good"}
_ANSWER = re.compile(r"^(?P<q>[^:=]{2,40}?)\s*[:=]\s*(?P<rest>.*\S)$")
_WHY = re.compile(r"\s+because\s+|\s+(?:—|–|--)\s+|\s*\(why:?\s*|\s*;?\s+why:\s*", re.IGNORECASE)  # not " - ": place names use it
_NOT_A_FIRE = re.compile(r"^not a fire\b(?P<rest>.*)$", re.IGNORECASE)
_SAME = re.compile(r"^(?:the )?(?:same (?:fire )?as|duplicate of)\s+F-?\s?(?P<n>\d+)\b(?P<rest>.*)$", re.IGNORECASE)
_ATTRIBUTION_END = re.compile(r"(?:wrote|a écrit|schrieb|escribió|ha scritto)\s*:?\s*$", re.IGNORECASE)
_ATTRIBUTION_START = re.compile(r"^(?:on|le|am|el|il|في)\s", re.IGNORECASE)
_CUT = re.compile(r"^(?:-{2,}\s*original message\s*-{2,}|_{10,}|--$|from:\s)", re.IGNORECASE)  # Outlook's quote, a signature
_NOISE = re.compile(r"^(?:sent from|envoyé de|get outlook)\b", re.IGNORECASE)


def own_words(text: str) -> str:
    """The reply without the e-mail it quotes, its signature and 'Sent from my phone'."""
    out: list[str] = []
    for line in text.replace("\r\n", "\n").split("\n"):
        s = line.strip()
        starts = bool(_ATTRIBUTION_START.match(s))
        if _CUT.match(s) or (starts and "@" in s and s.endswith(":")) or (
                _ATTRIBUTION_END.search(s) and (starts or (out and _ATTRIBUTION_START.match(out[-1].strip())))):
            if not starts and out and _ATTRIBUTION_START.match(out[-1].strip()):
                out.pop()  # "On Thu, … <" wrapped onto the line before "x@gmail.com> wrote:"
            break
        if not s.startswith(">") and not _NOISE.match(s):
            out.append(line)
    return "\n".join(out).strip()


def _why(rest: str) -> str:
    return re.sub(r"^[\s,.:;—–-]*(?:because\s+)?", "", rest, flags=re.IGNORECASE).strip(" .)")


def read(text: str) -> dict:
    """The verdict on the fire, the corrected answers with their reasons, and the lines that are neither."""
    corrections: dict[str, dict] = {}
    notes: list[str] = []
    ok, whole, same_as, why = False, None, None, ""
    for line in own_words(text).split("\n"):
        s = line.strip()
        if not s:
            continue
        if re.sub(r"[^\w\s]", "", s).strip().lower() in _OK:
            ok = True
        elif m := _NOT_A_FIRE.match(s):
            whole, why = whole or "not_a_fire", _why(m["rest"])
        elif m := _SAME.match(s):
            whole, same_as, why = whole or "same_fire", int(m["n"]), _why(m["rest"])
        elif (m := _ANSWER.match(s)) and (q := NAMES.get(re.sub(r"\s+", " ", m["q"]).strip().lower())):
            answer, *reason = _WHY.split(m["rest"], maxsplit=1)
            corrections[q] = {"answer": answer.strip(" ,.;"), "why": reason[0].strip(" .)") if reason else ""}
        else:
            notes.append(s)
    verdict = whole or ("corrected" if corrections else "ok" if ok else "unread")
    accepted = [q for q in QUESTIONS if q not in corrections] if verdict in ("ok", "corrected") else []
    return {"verdict": verdict, "corrections": corrections, "accepted": accepted, "same_as": same_as, "why": why,
            "notes": notes}


def _text(msg: EmailMessage) -> str:
    part = msg.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    text = part.get_content()
    if part.get_content_type() == "text/html":  # no plain version: drop the quoted e-mail, then the tags
        text = re.sub(r'(?is)<blockquote.*|<div[^>]*class="[^"]*gmail_quote.*', "", text)
        text = re.sub(r"(?i)<br\s*/?>|</(?:p|div|li|tr)>", "\n", text)
        text = html.unescape(re.sub(r"<[^>]+>", "", text))
    return text


# ---------------------------------------------------------------- who sent it

def authentic(msg: EmailMessage, review_address: str) -> bool:
    """From the review address (or its own domain), checked by the server that received it, and not automatic."""
    if str(msg.get("Auto-Submitted", "no")).strip().lower() != "no" or \
            str(msg.get("Precedence", "")).strip().lower() in ("bulk", "junk", "list", "auto_reply"):
        return False  # an out-of-office answer or a mailing, not a review
    sender, review = parseaddr(str(msg.get("From", "")))[1].lower(), review_address.strip().lower()
    domain = sender.rpartition("@")[2]
    if not domain or (sender != review and (domain != review.rpartition("@")[2] or domain in SHARED_DOMAINS)):
        return False
    results = msg.get_all("Authentication-Results") or []
    if not results:
        return False
    top = re.sub(r"\s+", " ", str(results[0])).lower()  # the receiving server's; any below it could be written by anyone
    d = re.escape(domain) + r"(?![\w.-])"
    return bool(re.search(rf"\bdmarc=pass\b[^;]*header\.from={d}", top)
                or re.search(rf"\bdkim=pass\b[^;]*header\.i=@{d}", top)
                or re.search(rf"\bspf=pass\b[^;]*smtp\.mailfrom=[^;\s]*@{d}", top))


# ---------------------------------------------------------------- a run

def fetch(settings: dict, since: dt.date) -> list[EmailMessage]:
    """The inbox's mail since `since`, left unread (the inbox is not this module's state)."""
    with imaplib.IMAP4_SSL(settings["IMAP_SERVER"], 993, timeout=60) as imap:
        imap.login(settings["MAIL_USERNAME"], settings["MAIL_PASSWORD"])
        imap.select("INBOX", readonly=True)
        _, data = imap.uid("SEARCH", None, "SINCE", f"{since.day}-{MONTHS[since.month - 1]}-{since.year}")
        out = []
        for uid in data[0].split():
            _, parts = imap.uid("FETCH", uid, "(BODY.PEEK[])")
            raw = next(p[1] for p in parts if isinstance(p, tuple))
            out.append(BytesParser(policy=policy.default).parsebytes(raw))
        return out


def record(msg: EmailMessage, store: Store, known: set[int]) -> dict:
    m = re.search(r"\bF-(\d+)\b", str(msg.get("Subject", "")))
    n = int(m[1]) if m and int(m[1]) in known else None
    text = own_words(_text(msg))
    said = read(text) if n is not None else read("") | {"notes": [text] if text else []}
    shown = store.root / "state" / "emailed" / f"F-{n}.json"
    try:
        received = parsedate_to_datetime(str(msg["Date"])).astimezone(BEIRUT).isoformat(timespec="minutes")
    except (TypeError, ValueError):
        received = None
    return {"message_id": str(msg["Message-ID"]).strip(), "fire": n, "received_at": received, **said, "text": text,
            "shown": json.loads(shown.read_text(encoding="utf-8")) if n is not None and shown.exists() else None}


def confirmation(rec: dict) -> str:
    """What was recorded, in the reviewer's terms, so a misread line is caught."""
    n, verdict = rec["fire"], rec["verdict"]
    if n is None:
        return ('Nothing recorded: I could not tell which fire this reply is about. Reply to the fire\'s own e-mail, '
                'keeping its number (like "F-12") in the subject.')
    why = f' (why: {rec["why"]})' if rec["why"] else ""
    lines = [{"not_a_fire": f"F-{n}: recorded as not a fire{why}.",
              "same_fire": f"F-{n}: recorded as the same fire as F-{rec['same_as']}{why}.",
              "unread": f"F-{n}: nothing recorded. I found no OK and no correction I can read."}.get(verdict, f"F-{n}: recorded.")]
    for q, c in rec["corrections"].items():
        lines.append(f"- {SHORT.get(q, q)}: {c['answer']}" + (f" (why: {c['why']})" if c["why"] else " (no reason given)"))
    if verdict == "ok":
        lines.append(f"- All {len(QUESTIONS)} answers: confirmed right.")
    elif verdict == "corrected":
        lines.append(f"- The other {len(rec['accepted'])} answers: confirmed right.")
    if rec["notes"]:
        lines += ["", "Kept as a note for a person to read, not as an answer:", *(f'- "{x}"' for x in rec["notes"])]
    if verdict == "unread" or rec["notes"]:
        lines += ["", f"To correct an answer, write one line: the question, the right answer, then why, e.g. {EXAMPLE}."]
    return "\n".join(lines)


def confirm(settings: dict, answered: list[tuple[EmailMessage, dict]]) -> None:
    with smtplib.SMTP_SSL(settings["MAIL_SERVER"], 465, timeout=60) as smtp:
        smtp.login(settings["MAIL_USERNAME"], settings["MAIL_PASSWORD"])
        for msg, rec in answered:
            out, subject = EmailMessage(), str(msg.get("Subject", "")).strip()
            out["Subject"] = subject if subject.lower().startswith("re:") else f"Re: {subject}"
            out["From"], out["To"] = formataddr((SENDER_NAME, settings["MAIL_USERNAME"])), str(msg["From"])
            out["In-Reply-To"] = rec["message_id"]
            out["References"] = f'{msg.get("References", "")} {rec["message_id"]}'.strip()
            out.set_content(confirmation(rec))
            smtp.send_message(out)


def run(store: Store | None = None, today: dt.date | None = None) -> dict:
    settings = _settings()
    if not settings:
        return {"recorded": 0, "mail": "not configured: nothing read"}
    settings |= {"IMAP_SERVER": os.environ.get("MAIL_IMAP_SERVER") or "imap.gmail.com"}
    store = store or Store()
    today = today or dt.datetime.now(BEIRUT).date()
    path, registry = store.root / "state" / "reviews.jsonl", store.root / "state" / "fires.json"
    kept = {json.loads(x)["message_id"] for x in path.read_text(encoding="utf-8").splitlines() if x.strip()} \
        if path.exists() else set()
    known = set(json.loads(registry.read_text(encoding="utf-8")).get("reports", {}).values()) if registry.exists() else set()
    answered, ignored = [], 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for msg in fetch(settings, today - dt.timedelta(days=WINDOW_DAYS)):
            mid = str(msg.get("Message-ID", "")).strip()
            if not mid or mid in kept:
                continue
            if not authentic(msg, settings["MAIL_TO"]):
                ignored += 1
                continue
            rec = record(msg, store, known)
            fh.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")
            fh.flush()
            kept.add(mid)
            answered.append((msg, rec))
    if answered:
        confirm(settings, answered)  # after the replies are kept: a failed answer loses no review
    verdicts = [r["verdict"] for _, r in answered]
    return {"recorded": len(answered), "ignored": ignored, **{v: verdicts.count(v) for v in sorted(set(verdicts))}}
