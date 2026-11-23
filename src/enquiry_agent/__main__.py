"""python -m enquiry_agent api|run|report|flags|faults|ci|demo

api     serve the made-up hotel's booking lookup on http://127.0.0.1:8077/availability
run     record any missing model calls (HEA_MODE=record), judge, and write results/
report  rebuild results/summary.json, the README tables and the chart from results/replies.jsonl and the audit
flags   list replies where the deterministic checks disagree with the judge, and whether each is reviewed
faults  run the missing-input and failed-dependency fixtures (scripted model, no API calls) and write results/faults.json
ci      replay every call from cassettes, check results reproduce exactly, and apply the gate (evals/gate.yaml)
demo    terminal walk-through of a few enquiries across the setups and the results table (for the demo video)
"""

import argparse
import json
import sys

from . import api, experiment, faults, readme


def _rows() -> list[dict]:
    return [json.loads(line) for line in (experiment.RESULTS / "replies.jsonl").read_text().splitlines()]


def main() -> int:
    ap = argparse.ArgumentParser(prog="enquiry_agent")
    ap.add_argument("cmd", choices=["api", "run", "report", "flags", "faults", "ci", "demo"])
    ap.add_argument("--models", nargs="*")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--pause", type=float, default=0.0)
    a = ap.parse_args()
    if a.cmd == "api":
        api.serve()
        return 0
    if a.cmd == "run":
        rows = experiment.run_all(tuple(a.models) if a.models else tuple(experiment.llm.MODELS), a.workers)
        summary = experiment.write(rows)
        readme.update(summary)
        print(json.dumps(summary["table"], indent=1))
        return 0
    if a.cmd == "report":
        readme.update(experiment.write(_rows()))
        from . import chart

        chart.main()
        return 0
    if a.cmd == "flags":
        audit = experiment.load_audit()
        for r in _rows():
            if r["flags"]:
                key = experiment.audit_key(r)
                print(f"{'reviewed' if key in audit else 'OPEN':<9}{key}  {'; '.join(r['flags'])}")
                print(f"         checks: {[p['detail'] for p in r['checks']['problems']]}")
                print(f"         judge:  {r['judge']}")
                print(f"         {r['reply'][:400]!r}")
        return 0
    if a.cmd == "faults":
        res = faults.write()
        readme.update_faults(res)
        print(faults.table(res))
        print(f"{res['passed']}/{res['cases']} as expected (22 Nov guard: {res['legacy_passed']}/{res['cases']})")
        return 0 if res["passed"] == res["cases"] else 1
    if a.cmd == "ci":
        from . import gate

        return gate.main()
    from . import demo

    demo.main(a.pause)
    return 0


if __name__ == "__main__":
    sys.exit(main())
