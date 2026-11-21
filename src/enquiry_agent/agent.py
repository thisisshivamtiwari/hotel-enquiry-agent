"""The three reply setups, plus the two booking-system-fault variants.

oneshot        the model gets the policy page and the guest message and writes the reply in one call
tools          the model can call check_availability (a JSON tool call in text, up to 3 times) before replying
guarded        tools, plus: lookups whose results don't parse or don't match the API's shape become an explicit
               "lookup failed" error; the reply goes through checks.check against the agent's own lookups and the
               handoff rules; one repair call if anything fails; if a hard problem is left, a safe handoff reply
tools_fault    tools, with the booking system returning a broken answer ({} or cut-off JSON) to every call
guarded_fault  guarded, with the same broken answers

The tool protocol is plain JSON in text because the replies are made through `claude -p` with built-in tools off;
each step is one recorded call (llm.py), so CI replays whole conversations.
"""

import json
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


def converse(alias: str, enquiry: dict, setup: str, n: int = 0) -> dict:
    tools = setup != "oneshot"
    guarded = setup.startswith("guarded")
    fault = setup.endswith("_fault")
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
        r = llm.call(alias, system, transcript + ask, purpose=f"{setup} {enquiry['id']} step {step}")
        calls.append(r)
        obj = llm.parse_json(r["text"])
        if tools and step < MAX_LOOKUPS and isinstance(obj, dict) and obj.get("tool") == "check_availability":
            args = obj.get("args") if isinstance(obj.get("args"), dict) else {}
            args = {k: v for k, v in args.items() if k in ("check_in", "nights", "adults", "children", "rooms", "room_type")}
            real = api.check_availability(**args) if "check_in" in args else api._error("bad_request", "check_in is required")
            raw = fake_fault(real, n) if fault else json.dumps(real)
            seen = well_formed(raw)
            if guarded and seen is None:
                seen, raw = LOUD_FAILURE, json.dumps(LOUD_FAILURE)
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
            r = llm.call(alias, system, prompt, purpose=f"{setup} {enquiry['id']} repair")
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
