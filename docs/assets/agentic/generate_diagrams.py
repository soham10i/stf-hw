"""Generate the static visuals used by the agentic-system feasibility report."""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

OUT = Path(__file__).resolve().parent
BG = "#07111f"
PANEL = "#0e1c2e"
PANEL_2 = "#12243a"
TEXT = "#edf5ff"
MUTED = "#9cb0c8"
TEAL = "#35d0ba"
BLUE = "#69a8ff"
AMBER = "#f6bd60"
RED = "#ff7b8a"
LINE = "#29415d"

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "text.color": TEXT,
    "axes.labelcolor": TEXT,
    "xtick.color": MUTED,
    "ytick.color": MUTED,
})


def canvas(title: str, subtitle: str, figsize=(16, 9)):
    fig, ax = plt.subplots(figsize=figsize, facecolor=BG)
    ax.set_facecolor(BG)
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis("off")
    ax.text(4, 96, title, fontsize=23, fontweight="bold", va="top")
    ax.text(4, 91.5, subtitle, fontsize=10.5, color=MUTED, va="top")
    return fig, ax


def box(ax, x, y, w, h, title, lines=(), color=BLUE, fill=PANEL, title_size=11, body_size=8.6):
    patch = FancyBboxPatch(
        (x, y), w, h, boxstyle="round,pad=0.45,rounding_size=1.4",
        linewidth=1.2, edgecolor=color, facecolor=fill,
    )
    ax.add_patch(patch)
    ax.text(x + 1.4, y + h - 2.1, title, fontsize=title_size, fontweight="bold", va="top", color=color)
    if lines:
        ax.text(x + 1.4, y + h - 5.5, "\n".join(lines), fontsize=body_size, color=TEXT, va="top", linespacing=1.5)
    return patch


def arrow(ax, start, end, color=MUTED, style="-|>", lw=1.5, connectionstyle="arc3,rad=0"):
    ax.add_patch(FancyArrowPatch(start, end, arrowstyle=style, mutation_scale=13,
                                linewidth=lw, color=color, connectionstyle=connectionstyle))


def save(fig, name):
    fig.savefig(OUT / name, dpi=180, facecolor=BG, bbox_inches="tight", pad_inches=0.25)
    plt.close(fig)


def architecture():
    fig, ax = canvas(
        "STF Agentic Digital Twin — recommended target",
        "Extend the working system; do not replace it. Blue = existing, teal = new boundary, amber = controlled addition.",
    )
    box(ax, 4, 75, 20, 11, "EXPERIENCE", ["3D twin + dashboard", "Approval / rejection card", "External MCP clients"], BLUE)
    box(ax, 29, 72, 42, 17, "EXISTING LANGGRAPH COPILOT", [
        "prepare → route → docs_rag / web / deep", "answer → verify → respond + traces", "Add mission subgraphs only where measured"], BLUE)
    box(ax, 76, 75, 20, 11, "MODEL POLICY", ["3.8 Flash default", "3.1 Pro after eval", "Free/local fallback"], AMBER)

    box(ax, 4, 54, 20, 12, "INTERFACES", ["REST / SSE / WS (keep)", "MCP Streamable HTTP", "No raw 30 Hz prompt feed"], TEAL)
    box(ax, 29, 51, 42, 18, "DETERMINISTIC MISSION CONTROL", [
        "Typed proposal + risk policy", "Fresh prechecks + approval binding", "Idempotency key + execute once", "Observe postcondition / escalate"], TEAL)
    box(ax, 76, 54, 20, 12, "INDEPENDENT SAFETY", ["PLC interlocks + E-stop", "Never model-controlled", "No compliance by assertion"], RED)

    box(ax, 4, 29, 28, 15, "RUNTIME & INDUSTRIAL I/O", ["SimRuntime / live hub", "Browser Wasm PLC + vision", "MQTT / OPC UA hardware adapters"], BLUE)
    box(ax, 37, 29, 31, 15, "SUPABASE POSTGRES", ["Existing factory + guest + pgvector", "Add checkpoints + approvals", "Durable hash-chained audit"], TEAL)
    box(ax, 73, 29, 23, 15, "CLOUD SERVICES", ["Cloud Run: stf-live", "Vertex AI + Cloud Trace", "Tasks / Pub/Sub when needed"], AMBER)

    box(ax, 16, 8, 68, 11, "EVIDENCE & DELIVERY GATES", [
        "Golden requests + evals  •  approval restart test  •  duplicate-execution test", "Token / latency / faithfulness budgets  •  staging before production"], BLUE, fill=PANEL_2)

    for x in (14, 50, 86):
        arrow(ax, (x, 75), (x, 69.5), TEAL if x == 50 else MUTED)
    arrow(ax, (50, 72), (50, 69.5), TEAL)
    arrow(ax, (50, 51), (22, 44.5), TEAL)
    arrow(ax, (50, 51), (52, 44.5), TEAL)
    arrow(ax, (86, 54), (60, 51.5), RED, connectionstyle="arc3,rad=0.12")
    arrow(ax, (52, 29), (52, 19.5), BLUE)
    arrow(ax, (84, 29), (74, 19.5), AMBER)
    ax.text(4, 3, "Raw telemetry stays in deterministic monitoring; models receive bounded snapshots and summaries.", color=MUTED, fontsize=9)
    save(fig, "target-architecture.png")


def workflow():
    fig, ax = canvas(
        "Complete agentic workflow — information, optimization and controlled action",
        "Solid arrows show the request path. The event path never calls an LLM per telemetry frame.",
        figsize=(17, 10),
    )
    box(ax, 4, 76, 19, 10, "OPERATOR REQUEST", ["Question, goal or command", "Guest + role + session"], BLUE)
    box(ax, 4, 57, 19, 11, "ANOMALY EVENT", ["1 Hz current watchdog", "Deduplicate / rate-limit", "No LLM per frame"], BLUE)
    box(ax, 29, 69, 18, 13, "MISSION INTAKE", ["Validate intent + schema", "Bind owner and budget", "Create mission / thread ID"], TEAL)

    box(ax, 54, 76, 18, 10, "READ / RESEARCH", ["Existing RAG + web graph", "Evidence + number check"], BLUE)
    box(ax, 54, 58, 18, 11, "OPTIMIZE", ["Deterministic solver first", "LLM explains trade-offs", "Return ranked plan"], AMBER)
    box(ax, 54, 38, 18, 12, "ACTION PROPOSAL", ["Typed operation + limits", "Risk classification", "Precheck current state"], TEAL)

    box(ax, 78, 58, 18, 11, "HUMAN APPROVAL", ["LangGraph interrupt", "Exact proposal + expiry", "Server-verified decision"], AMBER)
    box(ax, 78, 36, 18, 14, "GUARDED EXECUTION", ["Revalidate fresh state", "Execute once / idempotent", "Observe postcondition", "Persist signed audit"], RED)
    box(ax, 29, 37, 18, 13, "RESPONSE", ["Result + evidence + audit ID", "TTS: final content only", "Trace + token usage"], BLUE)

    arrow(ax, (23, 81), (29, 77), BLUE)
    arrow(ax, (23, 62.5), (29, 72), BLUE)
    arrow(ax, (47, 77), (54, 81), BLUE)
    arrow(ax, (47, 74), (54, 64), AMBER)
    arrow(ax, (47, 71), (54, 44), TEAL)
    arrow(ax, (72, 44), (78, 63), AMBER, connectionstyle="arc3,rad=-0.15")
    arrow(ax, (87, 58), (87, 50), AMBER)
    arrow(ax, (78, 40), (47, 42), RED)
    arrow(ax, (72, 81), (38, 50), BLUE, connectionstyle="arc3,rad=0.15")
    arrow(ax, (63, 58), (45, 50), AMBER, connectionstyle="arc3,rad=-0.1")

    box(ax, 7, 12, 86, 13, "FAILURE & RECOVERY RULES", [
        "Approval expires or state changed → reject / re-propose   •   Timeout → observe, compensate only if predefined, or escalate",
        "No automatic actuation retry   •   Resume from Postgres checkpoint   •   E-stop and protective interlocks remain outside the graph"], RED, fill=PANEL_2, body_size=9.2)
    arrow(ax, (87, 36), (80, 25), RED)
    save(fig, "agentic-workflow.png")


def roadmap():
    fig, ax = canvas(
        "Implementation sequence — gated increments inside a 60-day credit window",
        "Indicative effort for one developer, not a commitment. Every phase has a measurable stop/go gate.",
        figsize=(17, 8),
    )
    phases = [
        ("0", "BASELINE", "2–3 d", ["Fix 2 golden failures", "Record live metrics", "Freeze action surface"], BLUE),
        ("1", "VERTEX + EVAL", "3–5 d", ["Enable Vertex on staging", "Budgets + model ladder", "Compare quality / latency"], AMBER),
        ("2", "DURABLE ACTION", "5–8 d", ["Postgres checkpoints", "Approval API + UI", "Audit + idempotency"], TEAL),
        ("3", "MCP BOUNDARY", "3–5 d", ["Streamable HTTP /mcp", "Read resources first", "Scoped tools + auth"], TEAL),
        ("4", "SPECIALIZED MISSIONS", "5–8 d", ["Dispatch / diagnostics", "Solver-first optimization", "Event triage workers"], AMBER),
        ("5", "PRODUCTION GATE", "3–5 d", ["Restart / duplicate tests", "Load + alarm-flood tests", "Shadow → limited actions"], BLUE),
    ]
    x0, w, gap = 3, 14.7, 1.35
    for i, (num, name, days, lines, color) in enumerate(phases):
        x = x0 + i * (w + gap)
        box(ax, x, 39, w, 39, f"PHASE {num}", [name, days, "", *lines], color, title_size=10, body_size=8.2)
        if i < len(phases) - 1:
            arrow(ax, (x + w, 58), (x + w + gap, 58), MUTED)
    box(ax, 9, 15, 82, 13, "DO NOT BUILD YET", [
        "Cloud SQL duplication  •  BigQuery telemetry firehose  •  self-learning control  •  RL in the live safety loop",
        "Add these only after measured volume, evaluated benefit and an independent safety case."], RED, fill=PANEL_2, body_size=9.2)
    save(fig, "implementation-roadmap.png")


def costs():
    fast_38 = 15_000 / 1e6 * 0.75 + 2_500 / 1e6 * 3.75
    fast_35 = 15_000 / 1e6 * 1.50 + 2_500 / 1e6 * 9.00
    deep_pro = 100_000 / 1e6 * 2.00 + 8_000 / 1e6 * 12.00
    deep_38 = 100_000 / 1e6 * 0.75 + 8_000 / 1e6 * 3.75
    scenarios = {
        "Pilot": {"daily_fast": 20, "daily_pro": 0, "daily_deep_38": 2, "infra_60d": 5.0},
        "Busy / quality-first": {"daily_fast": 50, "daily_pro": 5, "daily_deep_38": 0, "infra_60d": 25.92},
        "Attached plan": {"daily_fast_35": 4000, "daily_pro": 80, "daily_deep_38": 0, "infra_60d": 39.0},
    }
    result = {}
    for name, s in scenarios.items():
        llm_day = (s.get("daily_fast", 0) * fast_38 + s.get("daily_fast_35", 0) * fast_35
                   + s["daily_pro"] * deep_pro + s["daily_deep_38"] * deep_38)
        result[name] = {"llm_usd_per_day": llm_day, "llm_usd_60d": llm_day * 60,
                        "infra_allowance_usd_60d": s["infra_60d"],
                        "total_usd_60d": llm_day * 60 + s["infra_60d"]}
    payload = {
        "assumptions": {
            "fast_tokens_in_out": [15000, 2500], "deep_tokens_in_out": [100000, 8000],
            "prices_usd_per_million": {"gemini_3_8_flash": [0.75, 3.75],
                                        "gemini_3_5_flash": [1.50, 9.00],
                                        "gemini_3_1_pro_preview": [2.00, 12.00]},
            "fast_cost_38": fast_38, "fast_cost_35": fast_35,
            "deep_cost_pro": deep_pro, "deep_cost_38": deep_38,
            "note": "Illustrative list-price scenarios, not a forecast. Excludes tax, FX, egress and any grounding overage.",
        },
        "scenarios": result,
    }
    (OUT / "cost-model.json").write_text(json.dumps(payload, indent=2) + "\n")

    fig, ax = plt.subplots(figsize=(13, 7.5), facecolor=BG)
    ax.set_facecolor(BG)
    names = list(result)
    vals = [result[n]["total_usd_60d"] for n in names]
    bars = ax.barh(names, vals, color=[TEAL, BLUE, RED], height=0.5)
    ax.set_xscale("log")
    ax.set_xlim(20, 30000)
    ax.axvline(250, color=AMBER, linestyle="--", linewidth=1.8, label="Stated 60-day credit ceiling (250)")
    ax.set_title("Illustrative 60-day model + infrastructure cost", loc="left", fontsize=20,
                 fontweight="bold", pad=24)
    ax.text(0, 1.025, "USD list-price arithmetic • logarithmic axis • measured usage must replace assumptions",
            transform=ax.transAxes, color=MUTED, fontsize=10)
    ax.set_xlabel("Estimated 60-day cost (USD, log scale)")
    ax.grid(axis="x", color=LINE, alpha=0.65)
    ax.set_axisbelow(True)
    for spine in ax.spines.values():
        spine.set_visible(False)
    for bar, name in zip(bars, names):
        v = result[name]["total_usd_60d"]
        label = f"${v:,.2f}" if v < 1000 else f"${v:,.0f}"
        ax.text(v * 1.12, bar.get_y() + bar.get_height() / 2, label, va="center", color=TEXT,
                fontsize=12, fontweight="bold")
    ax.legend(loc="lower right", frameon=False, labelcolor=TEXT)
    fig.tight_layout()
    save(fig, "cost-scenarios.png")


if __name__ == "__main__":
    architecture()
    workflow()
    roadmap()
    costs()
    print("Generated architecture, workflow, roadmap and cost visuals in", OUT)
