"""results/summary.json -> media/results.png: for each setup and model, how many replies could go to the guest as they
are and, if not, the first reason why."""

import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from . import experiment  # noqa: E402

SETUPS = {
    "oneshot": "one-shot prompt",
    "tools": "tool-grounded\nagent",
    "guarded": "tools + checks +\nrepair + handoff rules",
    "tools_fault": "tool agent,\nbooking system broken",
    "guarded_fault": "guarded,\nbooking system broken",
}
MODELS = {"haiku-4.5": "Haiku", "sonnet-5.5": "Sonnet"}
PARTS = [
    ("ready", "ready to send", "#1f6f50"),
    ("invented", "invented a price, availability or fact", "#c4472b"),
    ("unsafe", "unsafe (promise, injection, leak)", "#7a2e8c"),
    ("handoff", "wrong handoff", "#e0a526"),
    ("answer", "incomplete or wrong answer", "#8fb3d9"),
    ("check", "failed a hard check or missed the booking link", "#d9d8d4"),
]
INK, MUTED, SURFACE = "#0b0b0b", "#52514e", "#fcfcfb"


def main() -> None:
    s = json.loads((experiment.RESULTS / "summary.json").read_text())
    rows = {(r["model"], r["setup"]): r for r in s["table"]}
    fig, ax = plt.subplots(figsize=(13, 5.4), facecolor=SURFACE)
    ax.set_facecolor(SURFACE)
    xs, labels = [], []
    top = max(r["replies"] for r in s["table"])
    for i, setup in enumerate(SETUPS):
        for k, model in enumerate(MODELS):
            r = rows.get((model, setup))
            if r is None:
                continue
            parts = {"ready": r["ready"], **r["not_ready"]}
            x = i * 2.6 + k * 1.05
            xs.append(x)
            labels.append(MODELS[model])
            bottom = 0
            for key, name, colour in PARTS:
                v = parts.get(key, 0)
                ax.bar(
                    x,
                    v,
                    0.95,
                    bottom=bottom,
                    color=colour,
                    edgecolor=SURFACE,
                    linewidth=1,
                    label=name if not i and not k else None,
                )
                if key == "ready" and v:
                    ax.text(
                        x, v - 0.8, f"{v}/{r['replies']}", ha="center", va="top", fontsize=9, color="white", fontweight="bold"
                    )
                bottom += v
        ax.text(i * 2.6 + 0.52, -2.5, SETUPS[setup], ha="center", va="top", fontsize=9, color=INK)
    ax.set_xticks(xs, labels, fontsize=8, color=MUTED)
    ax.set_ylim(0, top + 1)
    ax.set_title(
        "Replies to made-up guest enquiries: could the reply go to the guest as it is? (Claude Haiku 4.5 and Sonnet 5.5)",
        fontsize=10.5,
        color=INK,
        loc="left",
    )
    ax.tick_params(colors=MUTED, length=0)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color("#d9d8d4")
    ax.legend(frameon=False, labelcolor=MUTED, fontsize=8.5, loc="upper left", bbox_to_anchor=(1.0, 1.0))
    note = (
        "51 enquiries to one made-up hotel; broken booking system = the 17 enquiries with dates it can answer, every lookup "
        "returning {} or cut-off JSON.\nNot ready = the first reason that applies, in the legend's order. "
        "Judge: Claude Sonnet 5.5 plus deterministic checks; disagreements reviewed by hand."
    )
    fig.text(0.01, 0.015, note, fontsize=8, color=MUTED, ha="left")
    fig.tight_layout(rect=(0, 0.08, 1, 1))
    (experiment.ROOT / "media").mkdir(exist_ok=True)
    fig.savefig(experiment.ROOT / "media" / "results.png", dpi=150)
