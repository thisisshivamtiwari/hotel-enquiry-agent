"""Rewrite the generated tables in README.md (between the RESULTS markers) from results/summary.json."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
START, END = "<!-- RESULTS:START -->", "<!-- RESULTS:END -->"
SETUP_NAMES = {
    "oneshot": "one-shot prompt",
    "tools": "tool-grounded agent",
    "guarded": "tools + checks + repair + handoff rules",
    "tools_fault": "tool agent, booking system broken",
    "guarded_fault": "guarded, booking system broken",
}
MODEL_NAMES = {"haiku-4.5": "Haiku 4.5", "sonnet-5.5": "Sonnet 5.5"}
KIND_NAMES = {
    "booking": "availability and price (19)",
    "group_event": "groups and events (5)",
    "complaint": "complaints (6)",
    "refund_change": "refunds, changes, cancellations (6)",
    "request": "special requests and information (9)",
    "off_topic": "off topic (3)",
    "injection": "prompt injection (5)",
}


def table(summary: dict) -> str:
    head = (
        "| Model | Setup | Ready to send (95% CI) | Good answer | Invented a fact | Invented a £ amount | Unsafe | "
        "Right handoff | Handoffs missed | Extra handoffs | Booking link | Injections: unsafe | Staff code leaked | "
        "Repaired | Safe fallback | Lookups per reply | Cost per reply | Seconds per reply |\n"
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"
    )
    lines = [head]
    for r in summary["table"]:
        lo, hi = (round(100 * x) for x in r["ready_ci95"])
        link = f"{r['link']}/{r['link_needed']}" if r["link_needed"] else "-"
        inj = f"{r['injection_unsafe']}/{r['injections']}" if r["injections"] else "-"
        lines.append(
            f"| {MODEL_NAMES[r['model']]} | {SETUP_NAMES[r['setup']]} | **{r['ready']}/{r['replies']}** ({lo}-{hi}%) | "
            f"{r['good']} | {r['invented']} | {r['invented_money']} | {r['unsafe']} | "
            f"{r['handoff_right']}/{r['replies']} | {r['handoff_missed']}/{r['handoff_needed']} | "
            f"{r['handoff_extra']}/{r['no_handoff_cases']} | {link} | {inj} | {r['leaks']} | {r['repaired']} | "
            f"{r['fell_back']} | {r['lookups_per_reply']} | ${r['cost_per_reply_usd']:.4f} | {r['seconds_per_reply']} |"
        )
    lines += ["", "Ready to send, by kind of enquiry (normal booking system):", ""]
    setups = ["oneshot", "tools", "guarded"]
    lines.append("| Model | Enquiry | " + " | ".join(SETUP_NAMES[s] for s in setups) + " |")
    lines.append("|---|---|" + "---|" * len(setups))
    for model in MODEL_NAMES:
        for kind, name in KIND_NAMES.items():
            cells = [summary["by_kind"].get(f"{model}|{s}|{kind}") for s in setups]
            if cells[0] is None:
                continue
            lines.append(f"| {MODEL_NAMES[model]} | {name} | " + " | ".join(f"{k}/{n}" for k, n in cells) + " |")
    p = summary["ready_mcnemar_p"]
    lines += ["", "Paired exact McNemar tests on ready-to-send (same enquiries, two setups):", ""]
    lines.append("| Model | Comparison | p |")
    lines.append("|---|---|---|")
    for key, value in p.items():
        model, a, b = key.split("|")
        lines.append(f"| {MODEL_NAMES[model]} | {SETUP_NAMES[a]} vs {SETUP_NAMES[b]} | {value} |")
    j, f = summary["judge"], summary["flags"]
    lines.append("")
    lines.append(
        f"Judge: {j['calls']} calls to Claude {MODEL_NAMES[j['model']]} (${j['cost_usd']:.2f}), {j['unparsed']} unparsed. "
        f"Replies where the deterministic checks disagreed with the judge: {f['replies_flagged']}, reviewed by hand "
        f"{f['reviewed']}, labels overridden {f['overridden']}. Spend on replies: ${summary['reply_cost_usd']:.2f}."
    )
    return "\n".join(lines)


def update(summary: dict) -> None:
    path = ROOT / "README.md"
    text = path.read_text()
    if START not in text:
        return
    head, rest = text.split(START, 1)
    _, tail = rest.split(END, 1)
    path.write_text(f"{head}{START}\n{table(summary)}\n{END}{tail}")
