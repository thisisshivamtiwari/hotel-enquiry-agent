"""A terminal walk-through for the demo video: a few made-up enquiries, what each setup replied (and what the guard
caught), then the results table. Reads results/ only; no model calls."""

import json
import textwrap
import time

from . import experiment

SHOW = (("b02", "haiku-4.5"), ("b10", "sonnet-5.5"), ("i01", "haiku-4.5"), ("c03", "sonnet-5.5"))
SETUPS = ("oneshot", "tools", "guarded")
NAMES = {
    "oneshot": "ONE-SHOT",
    "tools": "TOOLS",
    "guarded": "GUARDED",
    "tools_fault": "TOOLS, API BROKEN",
    "guarded_fault": "GUARDED, API BROKEN",
}


def _say(line: str = "", pause: float = 0.0) -> None:
    print(line, flush=True)
    if pause:
        time.sleep(pause)


def main(pause: float = 0.5) -> None:
    rows = [json.loads(line) for line in (experiment.RESULTS / "replies.jsonl").read_text().splitlines()]
    audit = experiment.load_audit()
    by = {(r["model"], r["setup"], r["id"]): r for r in rows}
    _say("HOTEL  Fernhollow House (made-up)  ·  today: Mon 1 Feb 2027  ·  booking system: a local fake API", pause)
    for eid, model in SHOW:
        first = by[(model, "oneshot", eid)]
        _say()
        _say(f"GUEST ({first['channel']})  " + " ".join(first["guest"].split())[:150], pause)
        for setup in SETUPS:
            r = by[(model, setup, eid)]
            why = experiment.reason(r, audit)
            verdict = "READY" if why is None else f"NOT READY: {why}"
            extra = f", {len(r['lookups'])} lookup(s)" if r["lookups"] else ""
            extra += ", repaired" if r["repaired"] else ""
            extra += ", safe fallback" if r["fell_back"] else ""
            _say(f"  {NAMES[setup]:<10}{model:<11} -> {verdict}  (handoff: {r['handoff']}{extra})", pause / 2)
            for line in textwrap.wrap(r["reply"].replace("\n", " "), 92)[:2]:
                _say(f"      {line}", pause / 6)
    _say()
    _say("RESULTS  51 made-up enquiries (19 with dates for the broken-API runs); ready = could go to the guest as is", pause)
    summary = json.loads((experiment.RESULTS / "summary.json").read_text())
    _say(f"  {'model':<11}{'setup':<20}{'ready':>8}{'invented':>10}{'unsafe':>8}{'handoff ok':>12}{'$/reply':>9}{'s/reply':>9}")
    for r in summary["table"]:
        _say(
            f"  {r['model']:<11}{NAMES[r['setup']]:<20}{r['ready']:>5}/{r['replies']:<2}{r['invented']:>10}{r['unsafe']:>8}"
            f"{r['handoff_right']:>9}/{r['replies']:<2}{r['cost_per_reply_usd']:>9.4f}{r['seconds_per_reply']:>9}",
            pause / 2,
        )
