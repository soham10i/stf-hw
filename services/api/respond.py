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

STYLES = {
    "greeting": "Answer with one or two friendly sentences; say what you can help with.",
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
    "research": "Answer in short sections with ### headings: what the sources say (every claim "
    "linked to its page), where they agree or differ, and what it means for this twin. Up to 350 "
    "words.",
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
        str: Style identifier key ('greeting', 'derive', 'compare', 'steps', 'status', 'list', 'explain', 'quick', or 'answer').
    """
    q = question.strip()
    if GREETING.match(q):
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
