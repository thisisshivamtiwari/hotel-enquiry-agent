"""The three reply setups, plus the two booking-system-fault variants.

oneshot        the model gets the policy page and the guest message and writes the reply in one call
tools          the model can call check_availability (a JSON tool call in text, up to 3 times) before replying
guarded        tools, plus: lookups whose results don't parse, don't match the API's shape, answer a different search
               or leave out room types the API always lists become an explicit "lookup failed" error (lookup_state);
               the reply goes through checks.check against the agent's own lookups and the handoff rules; one repair
               call if anything fails; if a hard problem is left, a safe handoff reply
tools_fault    tools, with the booking system returning a broken answer ({} or cut-off JSON) to every call
guarded_fault  guarded, with the same broken answers

The tool protocol is plain JSON in text because the replies are made through `claude -p` with built-in tools off;
each step is one recorded call (llm.py), so CI replays whole conversations. `converse` takes the booking system and
the model call as arguments so faults.py can run the same loop with a broken booking system and a scripted model.
"""

import json
import math
from pathlib import Path

from . import api, checks, llm

ROOT = Path(__file__).resolve().parents[2]
PROMPTS = ROOT / "prompts"
SETUPS = ("oneshot", "tools", "guarded")
FAULT_SETUPS = ("tools_fault", "guarded_fault")
MAX_LOOKUPS = 3
TEAMS = ("none", "reservations", "events", "guest_relations")
LOUD_FAILURE = {
    "error": "lookup_failed",
    "message": "The booking system did not answer properly. Do not quote any price or availability; tell the guest a "
    "colleague will confirm, and hand off to reservations.",
}


def system_prompt(tools: bool) -> str:
    return (
        (PROMPTS / "agent.txt")
        .read_text()
        .format(
            tools_rule=" and the booking system results" if tools else "",
            staff_code=api.hotel()["staff_code"],
            policy=api.policy(),
            tools=(PROMPTS / "tools.txt").read_text() if tools else "",
        )
    )


def fake_fault(result: dict, n: int) -> str:
    """A quiet failure: an empty object for even-numbered enquiries, JSON cut off part-way for odd ones."""
    text = json.dumps(result)
    return "{}" if n % 2 == 0 else text[: int(len(text) * 0.4)]


def lookup(args: dict) -> dict:
    """The booking system's answer for a tool call. A call without the stay's dates or party size is a bad request
    (before 23 Nov a call without nights or adults raised TypeError and stopped the run)."""
    if "check_in" not in args:
        return api._error("bad_request", "check_in is required")
    missing = [k for k in ("nights", "adults") if k not in args]
    if missing:
        return api._error("bad_request", f"{' and '.join(missing)} required")
    return api.check_availability(**args)


def well_formed(text: str) -> dict | None:
    """The guarded wrapper: a result that isn't valid JSON in the API's shape is a failure, not an empty answer."""
    try:
        r = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(r, dict):
        return None
    if "error" in r and "message" in r:
        return r
    opts = r.get("options")
    if isinstance(opts, list) and all(isinstance(o, dict) and {"room_type", "available"} <= o.keys() for o in opts):
        return r
    return None


def expected_rooms(args: dict) -> list[str] | None:
    """The room types a correct answer to `args` lists: every type that fits the party, free or not (the API's
    contract). None if the args aren't numbers, in which case only a bad_request answer is right."""
    try:
        adults, children, rooms = int(args["adults"]), int(args.get("children") or 0), int(args.get("rooms") or 1)
    except (KeyError, TypeError, ValueError):
        return None
    per_room = math.ceil((adults + children) / max(rooms, 1))
    want = args.get("room_type")
    return [t for t, info in api.hotel()["rooms"].items() if (not want or t == want) and per_room <= info["sleeps"]]


def lookup_state(text: str, args: dict) -> tuple[str, dict | None]:
    """Keep three things apart that a quiet failure blurs:

    verified  a real answer to this search: rooms and rates, or the API's own refusal (past date, not open, group)
    missing   the search itself lacked or garbled an input (bad_request): nothing is known about the stay yet
    failed    the booking system didn't answer this search: unparseable, wrong shape, an answer for other dates or
              party (a stale or cached result), or a room list missing types the API always lists (an empty list)
    """
    r = well_formed(text)
    if r is None or r.get("error") == "lookup_failed":
        return "failed", None
    if "error" in r:
        return ("missing" if r["error"] == "bad_request" else "verified"), r
    try:
        asked = {
            "check_in": str(args["check_in"]),
            "nights": int(args["nights"]),
            "adults": int(args["adults"]),
            "children": int(args.get("children") or 0),
            "rooms": int(args.get("rooms") or 1),
        }
    except (KeyError, TypeError, ValueError):
        return "failed", None
    if any(r.get(k) != v for k, v in asked.items()):
        return "failed", None
    if [o["room_type"] for o in r["options"]] != expected_rooms(args):
        return "failed", None
    return "verified", r


def _final(obj, text: str) -> dict:
    if isinstance(obj, dict) and isinstance(obj.get("reply"), str):
        out = {k: obj.get(k) for k in ("category", "reply", "handoff", "note_for_staff")}
        out["handoff"] = out["handoff"] if out["handoff"] in TEAMS else "none"
        out["format_error"] = False
        return out
    return {"category": None, "reply": text.strip(), "handoff": "none", "note_for_staff": "", "format_error": True}


def fallback_reply(team: str) -> str:
    c = api.hotel()["contacts"]
    who = {
        "events": f"our events team ({c['events']['email']})",
        "guest_relations": f"our guest relations team ({c['guest_relations']['email']})",
    }.get(team, f"our reservations team ({c['reservations']['email']}, {c['reservations']['phone']})")
    return (
        f"Thank you for your message. A colleague from {who} will reply to you personally, usually within one working "
        "day.\n\nThe Fernhollow team"
    )


def converse(alias: str, enquiry: dict, setup: str, n: int = 0, booking=None, call=llm.call) -> dict:
    """One enquiry through one setup. `booking(args) -> str` is the raw tool result (it may raise, like a timeout);
    the default is the fake booking API, quietly broken in the _fault setups."""
    tools = setup != "oneshot"
    guarded = setup.startswith("guarded")
    fault = setup.endswith("_fault")
    if booking is None:

        def booking(args: dict) -> str:
            return fake_fault(lookup(args), n) if fault else json.dumps(lookup(args))

    system = system_prompt(tools)
    transcript = f"GUEST MESSAGE ({enquiry['channel']}):\n{enquiry['text'].strip()}\n"
    calls, steps, lookups = [], [], []
    final = None
    for step in range(MAX_LOOKUPS + 1):
        if not tools:
            ask = "\nWrite the reply now as the JSON object."
        elif step == MAX_LOOKUPS:
            ask = "\nNo more lookups: reply now with the final JSON object."
        else:
            ask = "\nYour next step: one JSON object (a tool call or the final reply)."
        r = call(alias, system, transcript + ask, purpose=f"{setup} {enquiry['id']} step {step}")
        calls.append(r)
        obj = llm.parse_json(r["text"])
        if tools and step < MAX_LOOKUPS and isinstance(obj, dict) and obj.get("tool") == "check_availability":
            args = obj.get("args") if isinstance(obj.get("args"), dict) else {}
            args = {k: v for k, v in args.items() if k in ("check_in", "nights", "adults", "children", "rooms", "room_type")}
            try:
                raw = booking(args)
            except (TimeoutError, OSError) as e:
                raw = f"{type(e).__name__}: {e}"
            if guarded:
                state, seen = lookup_state(raw, args)
                if state == "failed":
                    seen, raw = LOUD_FAILURE, json.dumps(LOUD_FAILURE)
            else:
                seen = well_formed(raw)
            if seen is not None:
                lookups.append(seen)
            steps.append({"call": args, "result": raw})
            transcript += f"\nTOOL CALL {step + 1}: {json.dumps(obj)}\nTOOL RESULT {step + 1}: {raw}\n"
            continue
        final = _final(obj, r["text"])
        break
    draft = dict(final)
    problems, repaired, fell_back, forced = [], False, False, None
    if guarded:
        problems = checks.check(final["reply"], lookups, enquiry["text"])
        if final["format_error"]:
            problems.append({"rule": "format", "detail": "the reply was not the JSON object"})
        forced = checks.required_handoff(final.get("category") or "", enquiry["text"], lookups)
        if forced and final["handoff"] != forced:
            problems.append(
                {"rule": "handoff", "detail": f"this must be handed off to {forced}: tell the guest that team will reply"}
            )
        if any(lu.get("error") == "lookup_failed" for lu in lookups) and final["handoff"] == "none":
            problems.append({"rule": "handoff", "detail": "the booking system failed: hand off to reservations"})
            forced = forced or "reservations"
        if problems:
            fix = (PROMPTS / "repair.txt").read_text().format(problems="\n".join(f"- {p['detail']}" for p in problems))
            prompt = f"{transcript}\nYOUR DRAFT:\n{json.dumps(draft, ensure_ascii=False)}\n\n{fix}"
            r = call(alias, system, prompt, purpose=f"{setup} {enquiry['id']} repair")
            calls.append(r)
            final = _final(llm.parse_json(r["text"]), r["text"])
            repaired = True
            if forced:
                final["handoff"] = forced
            left = [p for p in checks.check(final["reply"], lookups, enquiry["text"]) if p["rule"] in checks.HARD]
            if left or final["format_error"]:
                team = forced or (final["handoff"] if final["handoff"] != "none" else "reservations")
                final = {**final, "reply": fallback_reply(team), "handoff": team, "format_error": False}
                fell_back = True
    return {
        "reply": final["reply"],
        "handoff": final["handoff"],
        "category": final.get("category"),
        "note_for_staff": final.get("note_for_staff") or "",
        "format_error": final["format_error"],
        "draft": draft["reply"] if repaired else None,
        "guard_problems": problems,
        "repaired": repaired,
        "fell_back": fell_back,
        "lookups": steps,
        "calls": len(calls),
        "cost_usd": round(sum(c["cost_usd"] for c in calls), 6),
        "seconds": round(sum(c["ms"] for c in calls) / 1000, 2),
    }
