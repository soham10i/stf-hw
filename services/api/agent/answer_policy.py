"""
What happens to a claim nothing backs. The graph's verify node asks claims.py and verify.py what
an answer states without support, then this module decides, in this order:

    regenerate   an unbacked number, a claim the judge found unsupported, or an answer whose
                 claims are mostly unsupported, and the correction not yet spent: the answer
                 goes back once to the model that wrote it, with the claims it should drop or
                 back (Conversation.correct). One claim the words alone miss is not worth a
                 second model call on a rate-limited tier: the steps below handle it
    pass         nothing factual to check (a greeting, "I don't know"), or everything backed
    decline      a docs or twin answer that the evidence hardly backs (groundedness and
                 confidence both low, at least two claims): replaced by saying the documents do
                 not cover it, with the closest passages as citations
    strip        at most a third of the claims unsupported, each a sentence or list item of its
                 own: those sentences go, and the note says how many
    hedge        anything else unsupported: the text stands, the note names what is not backed

Web and deep-research answers are only ever hedged: their evidence is a search summary, not the
pages, so the words check is weaker there. The rules fallback (no model) is never changed - it
is built from the tools' own words - but it is still scored.

Then citations: every supported claim the model left uncited gets the label of the document
passage or web page that backs it, in the [label] form the dashboard renders as a numbered source,
so every answer from the documents carries citations to the passages it uses. A tool's reading is
not marked inline - the answer's facts list already shows where it came from - and spoken answers
are left unmarked.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .claims import Claim, Report

DECLINE_GROUNDEDNESS = 0.34
DECLINE_CONFIDENCE = 0.3
STRIP_SHARE = 1 / 3
REGENERATE_SHARE = 0.5  # more than this share unsupported: worth a second call
CORRECT_CLAIMS = 5  # claims named in one correction
LOCAL_MODES = ("docs", "twin")


@dataclass
class Decision:
    """The policy's verdict on one answer and the text it leaves."""

    action: str  # pass | strip | hedge | decline
    text: str
    note: str | None = None
    removed: list[str] = field(default_factory=list)
    hedged: list[str] = field(default_factory=list)


def to_correct(report: Report | None) -> list[str]:
    """The claims to send back with a correction (numbers go through verify.py's list): those
    the judge found unsupported, or all the unsupported ones when they are most of the answer."""
    if report is None:
        return []
    bad = [c for c in report.unsupported() if c.why != "number"]
    facts = report.facts()
    if len(facts) >= 2 and len(bad) > REGENERATE_SHARE * len(facts):
        return [c.plain for c in bad][:CORRECT_CLAIMS]
    return [c.plain for c in bad if c.why == "judge"][:CORRECT_CLAIMS]


def correction(bad: list[str], claims: list[str]) -> str:
    """What the model is told when its answer states what nothing backs."""
    parts = []
    if bad:
        parts.append(
            f"Your answer states {', '.join(bad)}, which neither CONTEXT nor any tool result "
            "contains."
        )
    if claims:
        listed = "\n".join(f"- {c}" for c in claims)
        parts.append(
            "These statements in your answer are not supported by CONTEXT or the tool results:\n"
            f"{listed}"
        )
    parts.append(
        "Rewrite the answer using only what CONTEXT and the tool results say - call a tool if "
        "you need a fact - cite each fact's source in square brackets, and leave out what you "
        "cannot back. Do not mention this correction."
    )
    return "\n\n".join(parts)


def _closest(report: Report, k: int = 3) -> list[str]:
    seen: list[str] = []
    for c in report.facts():
        if c.passage is not None:
            label = report.passages[c.passage].label
            if label not in seen and report.passages[c.passage].kind == "doc":
                seen.append(label)
    return seen[:k]


def strip(text: str, claims: list[Claim]) -> str:
    """The text without these claims' spans; an emptied list item or line goes too."""
    for c in sorted(claims, key=lambda c: -c.start):
        text = text[: c.start] + text[c.end :]
    lines = [ln for ln in text.split("\n") if not re.fullmatch(r"\s*([-*+]|\d{1,2}[.)])?\s*", ln)
             or not ln.strip()]
    out = re.sub(r"\n{3,}", "\n\n", "\n".join(lines))
    return re.sub(r"[ \t]{2,}", " ", out).strip()


def decide(text: str, report: Report | None, mode: str, confidence: float | None,
           rules: bool = False) -> Decision:
    """The action for an answer after its one correction (see the module's docstring)."""
    if rules or report is None:
        return Decision("pass", text)
    facts = report.facts()
    bad = report.unsupported()
    if not facts or not bad:
        return Decision("pass", text)
    g = report.groundedness() or 0.0
    names = [c.plain for c in bad]
    if mode not in LOCAL_MODES:
        return Decision("hedge", text, _hedge_note(names), hedged=names)
    if (len(facts) >= 2 and g < DECLINE_GROUNDEDNESS
            and (confidence is None or confidence < DECLINE_CONFIDENCE)):
        near = _closest(report)
        msg = ("I can't answer this reliably: the documents and the twin's data I was given "
               "do not cover it.")
        if near:
            msg += " The closest passages are " + ", ".join(f"[{x}]" for x in near) + "."
        return Decision("decline", msg, "Declined: the sources did not back the answer.",
                        removed=names)
    if len(bad) <= STRIP_SHARE * len(facts) and all(c.whole for c in bad):
        left = strip(text, bad)
        if left and len(left) >= 0.3 * len(text):
            n = len(bad)
            note = (f"Removed {n} statement{'s' if n > 1 else ''} the sources do not support.")
            return Decision("strip", left, note, removed=names)
    return Decision("hedge", text, _hedge_note(names), hedged=names)


def _hedge_note(names: list[str]) -> str:
    shown = "; ".join(f'"{n[:90]}{"..." if len(n) > 90 else ""}"' for n in names[:3])
    more = f" and {len(names) - 3} more" if len(names) > 3 else ""
    return f"Not backed by the sources: {shown}{more} - check before relying on it"


def cite(text: str, report: Report | None, voice: bool = False) -> tuple[str, int]:
    """The text with a [label] after each supported claim that cites nothing, and how many
    citations were added. A claim is matched in the text by its span, so the text must be the
    one the report was made from."""
    if report is None or voice:
        return text, 0
    added = 0
    for c in sorted(report.facts(), key=lambda c: -c.end):
        if c.cited or c.verdict != "supported" or c.passage is None:
            continue
        p = report.passages[c.passage]
        if p.kind not in ("doc", "web"):
            continue  # a tool's reading, the page context or the operator's words: not cited
        span = text[c.start : c.end]
        if span != c.text:
            continue  # the text moved under the report: leave it
        end = c.start + len(span.rstrip())
        text = text[:end] + f" [{p.label}]" + text[end:]
        c.cited = [p.label]
        added += 1
    return text, added


def coverage(report: Report | None) -> float | None:
    """Checkable claims that carry a citation (the model's own or one added by cite)."""
    if report is None:
        return None
    facts = report.facts()
    return sum(1 for c in facts if c.cited) / len(facts) if facts else None
