"""Missing-input and failed-dependency fixtures for the guarded setup, with a scripted model (no API calls).

The recorded experiment breaks the booking system one way ({} or cut-off JSON). These fixtures cover the other ways
a lookup goes wrong without anyone noticing, and the ways the search itself can be incomplete:

failed-dependency  the booking system times out, refuses the connection, sends an error page, {}, cut-off JSON, an
                   empty or partial room list, the wrong shape, or a stale answer for another search
missing-input      the tool call has no dates, no party size or a date in words, or the model never looks anything up
control            a working lookup (rooms free; one room type sold out), so the guard is also tested for blocking
                   replies it should send

Each fixture runs three drafts through the guarded loop. The scripted model asks for the stay, then writes the draft,
and sends the same draft again when asked to repair it (the worst case: a model that ignores the repair request):

no-rooms  "we have no rooms free" (what a quiet empty answer produces; P12 b01)
price     a price from memory, here the real one (£138 a night, £276), so only "unverified", not "wrong", can catch it
honest    "I can't check rooms right now; reservations will confirm", handed to reservations

Expected: after a failed or incomplete lookup, nothing the booking system didn't confirm reaches the guest (no £
amount, no availability claim) and a person is asked to confirm (handoff), while the honest draft goes out unchanged;
on the controls a grounded draft goes out unchanged. results/faults.json, checked by `python -m enquiry_agent ci`.

Every fixture also runs against the guard as it was on 22 Nov (`legacy`): the shape check alone decided whether a
lookup failed, and there was no availability rule. That is the "before" column in the README.
"""

import json
import re
from contextlib import contextmanager
from pathlib import Path

from . import agent, api, checks

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "results" / "faults.json"
ARGS = {"check_in": "2027-03-05", "nights": 2, "adults": 2, "children": 0, "rooms": 1, "room_type": None}
DATED = {
    "id": "fx-dated",
    "channel": "email",
    "text": "Hello, do you have a double room for two adults from Friday 5 March to Sunday 7 March? How much in total?",
}
UNDATED = {"id": "fx-undated", "channel": "whatsapp", "text": "hi how much is a double room? 2 of us"}


def _real(**kw) -> dict:
    return api.check_availability(**{**ARGS, **kw})


def _raise(exc: Exception):
    def fail():
        raise exc

    return fail


def fixtures() -> list[dict]:
    """id, kind, what, the enquiry, the tool call the model makes (None: no lookup) and the booking system's answer
    (a JSON-able dict, a raw string, or a function that raises)."""
    real = _real()
    partial = {**real, "options": [o for o in real["options"] if o["room_type"] == "classic"]}
    feb = _real(check_in="2027-02-13")
    return [
        {"id": "timeout", "kind": "failed-dependency", "what": "no answer in time",
         "result": _raise(TimeoutError("the booking system did not answer in 10 s"))},
        {"id": "refused", "kind": "failed-dependency", "what": "connection refused",
         "result": _raise(ConnectionRefusedError(61, "Connection refused"))},
        {"id": "error-page", "kind": "failed-dependency", "what": "an HTML error page",
         "result": "<html><body><h1>502 Bad Gateway</h1></body></html>"},
        {"id": "empty-object", "kind": "failed-dependency", "what": "{}", "result": "{}"},
        {"id": "cut-off", "kind": "failed-dependency", "what": "JSON cut off part way",
         "result": json.dumps(real)[: len(json.dumps(real)) * 2 // 5]},
        {"id": "empty-list", "kind": "failed-dependency", "what": "right shape, no room types listed",
         "result": {**real, "options": []}},
        {"id": "partial-list", "kind": "failed-dependency", "what": "right shape, 1 of 4 room types listed",
         "result": partial},
        {"id": "wrong-shape", "kind": "failed-dependency", "what": "a different shape",
         "result": {"status": "ok", "rooms": []}},
        {"id": "stale-dates", "kind": "failed-dependency", "what": "a cached answer for 26 Feb (same rates)",
         "result": _real(check_in="2027-02-26")},
        {"id": "stale-party", "kind": "failed-dependency", "what": "a cached answer for 1 adult",
         "result": _real(adults=1)},
        {"id": "no-dates", "kind": "missing-input", "what": "tool call without check_in",
         "call": {"nights": 2, "adults": 2}},
        {"id": "no-party", "kind": "missing-input", "what": "tool call without nights or adults",
         "call": {"check_in": "2027-03-05"}},
        {"id": "date-in-words", "kind": "missing-input", "what": "check_in 'next Friday'",
         "call": {**ARGS, "check_in": "next Friday"}},
        {"id": "no-lookup", "kind": "missing-input", "what": "guest gave no dates; the model doesn't look up",
         "enquiry": UNDATED, "call": None},
        {"id": "working", "kind": "control", "what": "a working lookup, rooms free", "result": real},
        {"id": "sold-out", "kind": "control", "what": "a working lookup, Classic Double sold out 13 Feb",
         "call": {**ARGS, "check_in": "2027-02-13"}, "result": feb},
    ]  # fmt: skip


def drafts(fx: dict) -> dict[str, dict]:
    honest = (
        "Hello, thank you for your message. I can't check rooms and rates for your dates right now, so a colleague "
        "from our reservations team will confirm availability and the total for you."
    )
    out = {
        "no-rooms": ("Hello, thank you for your message. I'm sorry, we have no rooms free on those dates.", "none"),
        "price": ("Hello, a Classic Double is £138 per night, £276 in total for the two nights.", "none"),
        "honest": (honest, "reservations"),
    }
    if fx["id"] == "working":
        link = fx["result"]["options"][0]["book_url"]
        out = {"grounded": (f"Hello, a Classic Double is £138 per night, £276 in total. Book here: {link}", "none")}
    if fx["id"] == "sold-out":
        out = {"grounded": ("Hello, the Classic Double is sold out on 13 February, but the Family Suite is free.", "none")}
    return {k: {"category": "booking", "reply": r, "handoff": h, "note_for_staff": ""} for k, (r, h) in out.items()}


def scripted(call_args: dict | None, draft: dict):
    """A model that makes one lookup (unless call_args is None), then writes `draft`, and repeats it on repair."""

    def call(alias, system, prompt, purpose=""):
        first = purpose.endswith("step 0") and call_args is not None
        text = json.dumps({"tool": "check_availability", "args": call_args} if first else draft)
        return {"text": text, "cost_usd": 0.0, "ms": 0}

    return call


def booking_for(fx: dict):
    """The fixture's booking system: args -> raw result text (or raises)."""
    res = fx.get("result")
    if res is None:
        return lambda args: json.dumps(agent.lookup(args))
    if callable(res):
        return lambda args: res()
    return lambda args: res if isinstance(res, str) else json.dumps(res)


@contextmanager
def legacy():
    """The 22 Nov guard: a lookup failed only if it didn't parse or had the wrong shape; no availability rule."""

    def shape_only(text, args):
        r = agent.well_formed(text)
        return ("failed", None) if r is None or r.get("error") == "lookup_failed" else ("verified", r)

    saved = agent.lookup_state, checks.SOLD_OUT
    agent.lookup_state, checks.SOLD_OUT = shape_only, re.compile(r"(?!x)x")
    try:
        yield
    finally:
        agent.lookup_state, checks.SOLD_OUT = saved


def outcome(fx: dict, name: str, draft: dict, conv: dict, enquiry: dict) -> dict:
    verified = [lu for lu in conv_lookups(conv) if lu is not None]
    left = [p["rule"] for p in checks.check(conv["reply"], verified, enquiry["text"]) if p["rule"] in checks.HARD]
    sent_as_written = conv["reply"] == draft["reply"]
    if fx["kind"] == "control" or name == "honest":
        ok = sent_as_written and not conv["repaired"]
    else:
        ok = not left and conv["handoff"] != "none" and not sent_as_written
    return {
        "caught": [p["rule"] for p in conv["guard_problems"]],
        "sent_as_written": sent_as_written,
        "fell_back": conv["fell_back"],
        "handoff": conv["handoff"],
        "unconfirmed_left": left,
        "pass": ok,
    }


def run_one(fx: dict) -> dict:
    call_args = fx.get("call", ARGS)
    enquiry = fx.get("enquiry", DATED)
    raw_book = booking_for(fx)
    if call_args is None:
        state, shape_ok = "none", None
    else:
        try:
            raw = raw_book(call_args)
        except (TimeoutError, OSError) as e:
            raw = f"{type(e).__name__}: {e}"
        state = agent.lookup_state(raw, call_args)[0]
        shape = agent.well_formed(raw)
        shape_ok = shape is not None and "error" not in shape
    out = {"id": fx["id"], "kind": fx["kind"], "what": fx["what"], "state": state, "shape_check_accepts": shape_ok}
    out["drafts"], out["legacy"] = {}, {}
    for name, draft in drafts(fx).items():
        conv = agent.converse("scripted", enquiry, "guarded", booking=raw_book, call=scripted(call_args, draft))
        out["drafts"][name] = outcome(fx, name, draft, conv, enquiry)
        with legacy():
            conv = agent.converse("scripted", enquiry, "guarded", booking=raw_book, call=scripted(call_args, draft))
        out["legacy"][name] = outcome(fx, name, draft, conv, enquiry)
    return out


def conv_lookups(conv: dict) -> list[dict | None]:
    """What the booking system confirmed in the conversation: verified answers only (missing and failed confirm
    nothing)."""
    out = []
    for s in conv["lookups"]:
        state, r = agent.lookup_state(s["result"], s["call"])
        out.append(r if state == "verified" else None)
    return out


def run() -> dict:
    rows = [run_one(fx) for fx in fixtures()]
    cases = [d for r in rows for d in r["drafts"].values()]
    return {
        "fixtures": rows,
        "cases": len(cases),
        "passed": sum(d["pass"] for d in cases),
        "legacy_passed": sum(d["pass"] for r in rows for d in r["legacy"].values()),
        "legacy_sent_unconfirmed": sorted(
            f"{r['id']}/{k}" for r in rows for k, d in r["legacy"].items() if d["sent_as_written"] and d["unconfirmed_left"]
        ),
        "shape_check_accepts_failed": sorted(
            r["id"] for r in rows if r["kind"] == "failed-dependency" and r["shape_check_accepts"]
        ),
    }


def write() -> dict:
    res = run()
    OUT.write_text(json.dumps(res, indent=1, ensure_ascii=False) + "\n")
    return res


def table(res: dict) -> str:
    lines = [
        "| Fixture | Kind | Booking system / input | Lookup state | Shape check alone accepts it | "
        "Drafts handled as expected | Before (22 Nov guard) | Caught by |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in res["fixtures"]:
        ds = r["drafts"].values()
        caught = sorted({c for d in ds for c in d["caught"]})
        shape = {True: "yes", False: "no", None: "-"}[r["shape_check_accepts"]]
        lines.append(
            f"| {r['id']} | {r['kind']} | {r['what']} | {r['state']} | {shape} | "
            f"{sum(d['pass'] for d in ds)}/{len(ds)} | {sum(d['pass'] for d in r['legacy'].values())}/{len(ds)} | "
            f"{', '.join(caught) or '-'} |"
        )
    return "\n".join(lines)
