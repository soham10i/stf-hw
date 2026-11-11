"""
A transcript in the factory's own names, before it is asked: what a speech-to-text model writes
for the rack's slots and the machines' short names is not what the router and the tools match.

    "store a red one in a two"     -> "store a red one in A2"
    "fetch from slot bee three"    -> "fetch from slot B3"
    "how is the h b w doing"       -> "how is the HBW doing"

A slot is only rewritten after a word that names a place (slot, bay, from, to, in, into, at ...),
so "a two-minute wait" and "a one-off" stay as they were said. The rack has nine slots, A1 to C3
(actuation.py SLOT_RE). The words heard are kept beside the rewrite, so the operator sees both.
"""

from __future__ import annotations

import re

LETTER = {"a": "A", "ay": "A", "eh": "A", "b": "B", "be": "B", "bee": "B",
          "c": "C", "see": "C", "sea": "C", "si": "C"}
DIGIT = {"1": "1", "one": "1", "won": "1", "2": "2", "two": "2", "to": "2", "too": "2",
         "3": "3", "three": "3", "tree": "3"}
PLACE = r"slot|bay|position|place|shelf|from|to|in|into|at|on|out of"

_L = "|".join(sorted(map(re.escape, LETTER), key=len, reverse=True))
_D = "|".join(sorted(map(re.escape, DIGIT), key=len, reverse=True))
SLOT = re.compile(
    rf"\b(?P<lead>{PLACE})(?P<gap>\s+(?:slot\s+)?)(?P<l>{_L})[\s-]?(?P<d>{_D})\b(?![-\w])", re.I
)
# machine short names spelled out letter by letter
SPELLED = {
    "hbw": re.compile(r"\bh[\s.-]*b[\s.-]*w\b\.?", re.I),
    "vgr": re.compile(r"\bv[\s.-]*g[\s.-]*r\b\.?", re.I),
    "plc": re.compile(r"\bp[\s.-]+l[\s.-]+c\b\.?", re.I),
    "oee": re.compile(r"\bo[\s.-]+e[\s.-]+e\b\.?", re.I),
}


def canonical(text: str) -> str:
    """The transcript with slots and machine names written as the factory writes them."""
    out = SLOT.sub(
        lambda m: f"{m['lead']}{m['gap']}{LETTER[m['l'].lower()]}{DIGIT[m['d'].lower()]}", text
    )
    for name, pat in SPELLED.items():
        out = pat.sub(name.upper(), out)
    return out


def heard(result: dict) -> dict:
    """A transcription result with its text in the factory's names, and what was heard when
    the two differ."""
    raw = result.get("text") or ""
    text = canonical(raw)
    return {**result, "text": text, **({"heard": raw} if text != raw else {})}
