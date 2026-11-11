"""
Answers shaped by the kind of question.

A question is classified from its words and the tools it needs into one STYLE; the style tells the
model the format to answer in and tells the browser how to render it:

  greeting   one or two friendly sentences
  quick      one fact: the figure first, in bold, one sentence of meaning  -> a highlight card
  compare    two or more things side by side: a markdown table           -> a table
  steps      what to do (an alarm, a fault, a procedure): numbered steps  -> a checklist
  status     what the cell is doing now: short labelled bullets          -> a status card
  list       several items ranked or listed: bullets, most important first
  explain    how or why something works: two short paragraphs at most, bullets for parts
  derive     the mathematics of something: each step a sentence and its equation (LaTeX), a
             worked example from the twin's numbers
  research   a web or deep-research answer: what the sources say, linked, and what it means here
  answer     anything else: plain, short
"""

from __future__ import annotations

import re

from services.api.agent.orchestrate import is_conversational

STYLES = {
    "greeting": "Answer with one or two friendly sentences; say what you can help with.",
    "voice": (
        "Answer for voice: speak naturally and conversationally in 1 to 3 short sentences "
        "(under 60-80 words). No markdown tables, no bullet points, no display equations."
    ),
    "quick": "Lead with the key figure in **bold** and its unit, then one sentence on what it "
    "means. At most 40 words.",
    "compare": "Answer with a markdown table: one row per item compared, one column per measure, "
    "then one sentence naming the item that needs attention first.",
    "steps": "Answer with numbered steps the operator can follow, most urgent first; one line "
    "each. Start with one sentence saying what happened.",
    "status": "Answer with 3-6 short bullets, each '**label**: value'. No preamble.",
    "list": "Answer with bullets, most important first, each with its key figure in bold.",
    "explain": "Explain in at most two short paragraphs; use bullets for the parts of a mechanism.",
    "derive": "Explain the calculation step by step as a numbered list - never a table. For "
    "each step: one sentence on what it does and why, then its equation in LaTeX on a line of "
    "its own ($$...$$), defining each "
    "symbol once (inline $...$). Use the exact equations and numbers in CONTEXT, cite each step's "
    "source, and end with a short worked example from CONTEXT's numbers. Code, if any, in a "
    "fenced block with its language. Up to 450 words.",
    "research": (
        "Provide an extensive, publication-grade Deep Research Report (target 2,500–5,000+ words) "
        "formatted in structured Markdown with comprehensive comparative tables and mathematical derivations. "
        "Structure your report as follows:\n"
        "1. **Executive answer**: 2-3 high-density bullet points summarizing the core findings and numerical takeaways.\n"
        "2. **1. What the sources say**: A detailed Markdown table (| Source | Engine(s) evaluated | Test set | Key accuracy metrics | Real-time performance |) followed by evidence analysis.\n"
        "3. **2. Accuracy metrics – definitions & relevance**: Rigorous mathematical formulations with KaTeX/LaTeX block equations ($$...$$ on own line) and inline math ($...$) in a detailed table (| Metric | Formula (LaTeX) | What it measures | Why it matters for STF |), followed by physical derivations for RMSE, DTW, penetration depth $\\delta$, contact impulse/force, friction angle error $\\Delta\\theta$, energy loss, and momentum transfer efficiency.\n"
        "4. **3. Real-time constraints of the STF twin**: Timing breakdown and numerical bounds table for PLC/bus/simulation loop latency (e.g. 10 ms PLC cycle, 5 ms sub-task, bus round-trip latency).\n"
        "5. **4. Comparative analysis**: Cross-engine benchmark table comparing Bullet, ODE, Vortex, PhysX / Isaac Sim, and MuJoCo on contact accuracy, penetration depth, solve speed (Hz on CPU/GPU), and typical digital twin use cases, followed by deep solver mechanics (PGS, LCP, penalty springs, Baumgarte stabilization).\n"
        "6. **5. Implementation & verification recommendations**: Concrete architectural recommendations for predictive accuracy vs. deterministic cycle time."
    ),
    "answer": "Answer plainly and briefly.",
}
DERIVE = re.compile(
    r"\bmath|\bformula|\bequation|\bcalculat|\bderiv|\btheory behind|"
    r"how (is|are) .{1,40}\b(computed|calculated|derived|estimated)",
    re.I,
)

_RULES: list[tuple[str, re.Pattern]] = [
    (
        "compare",
        re.compile(
            r"\bcompare|\bvs\.?\b|versus|difference between|which is (worse|better|more)"
            r"|side by side",
            re.I,
        ),
    ),
    (
        "steps",
        re.compile(
            r"what (should|do) i do|how (do|can) i|what now|fix|troubleshoot|recover|reset|"
            r"steps?\b|procedure|popped up|shows? [A-Z]{3}-",
            re.I,
        ),
    ),
    (
        "status",
        re.compile(
            r"\bright now\b|\bnow\b|currently|at the moment|status|is the .* (hot|running|on)", re.I
        ),
    ),
    ("list", re.compile(r"\blist\b|which parts|all (the )?(parts|alarms)|top \d|rank", re.I)),
    (
        "explain",
        re.compile(r"\bhow does\b|\bwhy\b|explain|what is the purpose|how .* works?", re.I),
    ),
    ("quick", re.compile(r"^(what is|what's|how (much|many|long)|when)\b", re.I)),
]
GREETING = re.compile(
    r"^(hi|hello|hey|howdy|greetings|good\s+(morning|afternoon|evening))\b[\s!.,?]*$", re.I
)


def classify(question: str, tools: list[str] | None = None) -> str:
    """Classify user query and invoked tools into a target response presentation style.

    Args:
        question: User query text.
        tools: Optional list of executed tool names.

    Returns:
        str: Style identifier key ('greeting', 'derive', 'compare', 'steps', 'status',
        'list', 'explain', 'quick', or 'answer').
    """
    q = question.strip()
    if is_conversational(q):
        return "greeting"
    if DERIVE.search(q):
        return "derive"
    for style, rx in _RULES:
        if rx.search(q):
            return style
    if tools and "live_state" in tools:
        return "status"
    if tools and "alarm_lookup" in tools:
        return "steps"
    return "answer"


def instruction(style: str) -> str:
    """Format styling system prompt instruction for the LLM based on selected style.

    Args:
        style: Style identifier name.

    Returns:
        str: Formatted system instruction text.
    """
    return f"FORMAT ({style}): {STYLES.get(style, STYLES['answer'])}"
