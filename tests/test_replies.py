import datetime as dt
import json
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from typing import ClassVar

import pytest
from test_notify import ITEM, FakeSMTP, _store

from crawler import notify, replies

REVIEW = "review@reviewers.test"
PASSED = "mx.google.com; dkim=pass header.i=@reviewers.test; spf=pass smtp.mailfrom=review@reviewers.test"


def mail(body: str, subject: str = "Re: New fire F-1: Dump or landfill, Saida — 26 Oct 2026", sender: str = REVIEW,
         results: str | None = PASSED, mid: str = "<r1@reviewers.test>", **headers) -> EmailMessage:
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"], msg["Message-ID"] = sender, "sender@x.test", subject, mid
    msg["Date"] = "Wed, 28 Oct 2026 09:30:00 +0000"
    if results:
        msg["Authentication-Results"] = results
    for k, v in headers.items():
        msg[k.replace("_", "-")] = v
    msg.set_content(body)
    return BytesParser(policy=policy.default).parsebytes(msg.as_bytes())  # as it arrives


# ---------------------------------------------------------------- what a reply says

def test_ok_confirms_all_nine():
    said = replies.read("OK\n\nOn Wed, 28 Oct 2026 at 11:00, Lebanon fire incidents <sender@x.test> wrote:\n> Site: Dump")
    assert said["verdict"] == "ok" and said["corrections"] == {} and said["accepted"] == notify.QUESTIONS
    assert replies.read("Ok, thanks!")["verdict"] == "ok"


def test_one_line_per_wrong_answer_with_its_reason():
    said = replies.read("Site: warehouse because the article says depot\n"
                        "Origin = not stated — 'electrical' was a guess\n"
                        "location: بلدة تول - قضاء النبطية\n"
                        "what  burned: tyres (why: the photo)\n")
    assert said["verdict"] == "corrected" and said["notes"] == []
    assert said["corrections"] == {
        "Site that witnessed the fire": {"answer": "warehouse", "why": "the article says depot"},
        "Origin": {"answer": "not stated", "why": "'electrical' was a guess"},
        "Location": {"answer": "بلدة تول - قضاء النبطية", "why": ""},  # " - " is part of the place, not a reason
        "What burned": {"answer": "tyres", "why": "the photo"},
    }
    assert len(said["accepted"]) == 5 and "Origin" not in said["accepted"]


def test_whole_fire_verdicts():
    no = replies.read("Not a fire, it was a drill")
    assert (no["verdict"], no["why"]) == ("not_a_fire", "it was a drill")
    same = replies.read("Same fire as F-12 because both are the Fakra depot")
    assert (same["verdict"], same["same_as"], same["why"]) == ("same_fire", 12, "both are the Fakra depot")
    assert replies.read("duplicate of f-3")["same_as"] == 3
    assert replies.read("Not a fire")["accepted"] == []


def test_anything_else_is_a_note_never_a_guess():
    said = replies.read("I think this was in Tyre, not Saida\nSite: warehouse")
    assert said["verdict"] == "corrected" and said["notes"] == ["I think this was in Tyre, not Saida"]
    assert replies.read("Weather: windy")["verdict"] == "unread"  # not one of the nine questions
    assert replies.read("")["verdict"] == "unread"


@pytest.mark.parametrize("quote", [
    "On Wed, 28 Oct 2026 at 11:00, Lebanon fire incidents <sender@x.test> wrote:",
    "On Wed, 28 Oct 2026 at 11:00, Lebanon fire incidents <\nsender@x.test> wrote:",  # Gmail wraps it
    "Le mer. 28 oct. 2026 à 11:00, Lebanon fire incidents <sender@x.test> a écrit :",
    "في الأربعاء، 28 أكتوبر 2026 في 11:00 ص، كتب Lebanon fire incidents <sender@x.test>:",
    "-----Original Message-----\nFrom: Lebanon fire incidents",
    "________________________________\nFrom: Lebanon fire incidents",
])
def test_the_quoted_email_is_not_read(quote):
    text = f"Site: warehouse\n\nSent from my iPhone\n\n{quote}\nOK\nSite: Dump or landfill"
    assert replies.own_words(text) == "Site: warehouse"


def test_signature_is_not_read():
    assert replies.own_words("OK\n--\nThe review desk\nSite: x") == "OK"


# ---------------------------------------------------------------- who sent it

@pytest.mark.parametrize("sender,results,ok", [
    (REVIEW, PASSED, True),
    ("Desk <desk@reviewers.test>", "mx.google.com; spf=pass (domain of desk@reviewers.test) smtp.mailfrom=desk@reviewers.test",
     True),  # the reviewer's own domain, as an alias's replies come from the main address
    (REVIEW, "mx.google.com; dmarc=pass (p=NONE) header.from=reviewers.test", True),
    (REVIEW, None, False),  # nobody checked it
    (REVIEW, "mx.google.com; spf=fail smtp.mailfrom=review@reviewers.test", False),
    (REVIEW, "mx.google.com; spf=pass smtp.mailfrom=x@reviewers.test.evil.test", False),
    ("x@evil.test", "mx.google.com; spf=pass smtp.mailfrom=x@evil.test", False),
])
def test_only_the_review_address_counts(sender, results, ok):
    assert replies.authentic(mail("OK", sender=sender, results=results), REVIEW) is ok


def test_on_a_shared_provider_only_the_address_itself():
    passed = "mx.google.com; spf=pass smtp.mailfrom={}"
    assert replies.authentic(mail("OK", sender="review@gmail.com", results=passed.format("review@gmail.com")),
                             "review@gmail.com")
    assert not replies.authentic(mail("OK", sender="anyone@gmail.com", results=passed.format("anyone@gmail.com")),
                                 "review@gmail.com")


def test_only_the_top_check_counts():
    msg = mail("OK", results="mx.google.com; spf=fail smtp.mailfrom=review@reviewers.test")
    msg["Authentication-Results"] = PASSED  # written below the server's own, by the sender
    assert not replies.authentic(msg, REVIEW)


def test_automatic_answers_are_not_reviews():
    assert not replies.authentic(mail("I am away", Auto_Submitted="auto-replied"), REVIEW)
    assert not replies.authentic(mail("OK", Precedence="bulk"), REVIEW)


# ---------------------------------------------------------------- a run

class FakeIMAP:
    inbox: ClassVar[list[EmailMessage]] = []

    def __init__(self, host, port, timeout):
        assert (host, port) == ("imap.gmail.com", 993)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def login(self, user, password):
        assert (user, password) == ("sender@x.test", "app-password")

    def select(self, box, readonly):
        assert readonly  # the inbox is left as it was

    def uid(self, command, *args):
        if command == "SEARCH":
            assert args[1:] == ("SINCE", "28-Sep-2026")
            return "OK", [" ".join(str(i + 1) for i in range(len(self.inbox))).encode()]
        return "OK", [(b"1 (BODY[] {9})", self.inbox[int(args[0]) - 1].as_bytes()), b")"]


def test_each_reply_is_kept_once_with_what_the_email_showed(tmp_path, monkeypatch):
    store = _store(tmp_path, {"dump": [ITEM]})
    today = dt.date(2026, 10, 28)
    for k in ("MAIL_USERNAME", "MAIL_PASSWORD", "MAIL_TO"):
        monkeypatch.delenv(k, raising=False)
    assert replies.run(store, today) == {"recorded": 0, "mail": "not configured: nothing read"}

    monkeypatch.setenv("MAIL_USERNAME", "sender@x.test")
    monkeypatch.setenv("MAIL_PASSWORD", "app-password")
    monkeypatch.setenv("MAIL_TO", REVIEW)
    monkeypatch.setattr(notify.smtplib, "SMTP_SSL", FakeSMTP)
    monkeypatch.setattr(replies.imaplib, "IMAP4_SSL", FakeIMAP)
    FakeSMTP.sent = []
    notify.run(store, today)
    [fire_mail] = FakeSMTP.sent
    shown = json.loads((tmp_path / "state" / "emailed" / "F-1.json").read_text(encoding="utf-8"))
    assert shown["message_id"] == fire_mail["Message-ID"] and shown["answers"]["Site that witnessed the fire"]
    assert "the right answer, then why" in fire_mail.get_body(("plain",)).get_content()

    FakeIMAP.inbox = [
        mail("Site: warehouse because the article says depot\n\nOn Wed, … <sender@x.test> wrote:\n> OK", References=shown["message_id"]),
        mail("OK", sender="x@evil.test", results="mx.google.com; spf=pass smtp.mailfrom=x@evil.test", mid="<e@evil.test>"),
        mail("OK", subject="Re: hello", mid="<r2@reviewers.test>"),
    ]
    FakeSMTP.sent = []
    assert replies.run(store, today) == {"recorded": 2, "ignored": 1, "corrected": 1, "unread": 1}
    kept = [json.loads(x) for x in (tmp_path / "state" / "reviews.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [r["fire"] for r in kept] == [1, None]
    assert kept[0]["corrections"]["Site that witnessed the fire"]["answer"] == "warehouse"
    assert kept[0]["shown"]["answers"] == shown["answers"] and kept[0]["text"].startswith("Site: warehouse")
    assert all("evil" not in json.dumps(r) and REVIEW not in json.dumps(r) for r in kept)  # no addresses kept

    answer, unsure = FakeSMTP.sent
    assert answer["To"] == REVIEW and answer["In-Reply-To"] == "<r1@reviewers.test>"
    assert answer["Subject"].startswith("Re: New fire F-1") and shown["message_id"] in answer["References"]
    body = answer.get_content()
    assert "- Site: warehouse (why: the article says depot)" in body and "The other 8 answers: confirmed right" in body
    assert "could not tell which fire" in unsure.get_content()

    FakeSMTP.sent = []
    assert replies.run(store, today)["recorded"] == 0 and FakeSMTP.sent == []  # never twice


def test_the_confirmation_says_what_was_not_read():
    rec = {"fire": 4, "verdict": "unread", "why": "", "corrections": {}, "accepted": [], "same_as": None,
           "notes": ["looks off to me"]}
    text = replies.confirmation(rec)
    assert "nothing recorded" in text and '"looks off to me"' in text and "Site: warehouse because" in text
    assert "All 9 answers: confirmed right" in replies.confirmation(rec | {"verdict": "ok", "notes": []})
