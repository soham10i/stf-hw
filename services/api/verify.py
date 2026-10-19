"""
Is every number in an answer backed by the twin? The check the chat runs on each model answer
before it is shown, and the one the evaluation scores with (eval_copilot.py).

A number is backed when it appears in the evidence - the tools' results, the question, the
operator's own earlier messages - or follows from evidence numbers by the arithmetic an honest
answer does: rounding, a ratio as a percentage, hours as minutes, the sum or difference of two
of them. Years, list numbering and the small counting words 1-5 are not facts. Anything else is
unverified: 2.43 h told as "2 hours 43 minutes", a warning threshold no tool reported.
"""

from __future__ import annotations

import re

NUM = re.compile(r"(?<![\w.])-?\d+(?:[.,]\d+)?")
LIST_MARK = re.compile(r"(?m)^\s*\d{1,2}[.)]\s")
_CAP = 150  # evidence numbers combined pairwise


def _rounded(x: float) -> set[str]:
    """x as an honest answer may write it: rounded to 0, 1 or 2 decimals ("about 46 kWh")."""
    out = set()
    for d in (0, 1, 2):
        v = round(x, d)
        out.add(f"{v:.{d}f}".rstrip("0").rstrip(".") if d else str(int(v)))
    return {s.lstrip("-") or "0" for s in out}


def _exact(x: float) -> set[str]:
    """x only as written at the precision it really has: a derived number must not be rounded
    into backing something else (44 - 0.803 = 43.197 does not back "43")."""
    for d in (0, 1, 2):
        if abs(x - round(x, d)) < 0.005:
            v = round(x, d)
            return {(f"{v:.{d}f}".rstrip("0").rstrip(".") if d else str(int(v))).lstrip("-") or "0"}
    return {f"{x:.2f}".rstrip("0").rstrip(".").lstrip("-")}


def numbers(text: str) -> set[str]:
    """The numbers in a text, normalised (decimal comma -> point, no trailing zeros)."""
    out = set()
    for n in NUM.findall(text):
        s = n.replace(",", ".").lstrip("-")
        s = s.rstrip("0").rstrip(".") if "." in s else s
        out.add(s or "0")
    return out


def _floats(text: str) -> list[float]:
    xs = []
    for n in NUM.findall(text):
        try:
            xs.append(float(n.replace(",", ".")))
        except ValueError:
            pass
    return list(dict.fromkeys(xs))


def allowed(evidence: str, question: str = "") -> set[str]:
    """Calculate the set of allowable numerical strings derivable from ground-truth evidence.

    Permits:
      - Raw evidence and question numbers.
      - Numbers rounded to 0, 1, or 2 decimal places.
      - Unit conversions (e.g. hours to minutes).
      - Ratios expressed as percentages.
      - Pairwise sums and differences of decimal numbers.

    Args:
        evidence: Ground-truth tool results or retrieved documents.
        question: User query text.

    Returns:
        set[str]: Normalized string representations of verified permissible numbers.
    """
    xs = _floats(evidence)
    ok = numbers(evidence) | numbers(question)
    for a in xs:
        ok |= _rounded(a)
        if 0 < abs(a) <= 1.5:
            ok |= _rounded(a * 100)
        ok |= _exact(a * 60)
    # pairs: only of two measured decimals (e.g. saving between two costs, two energies)
    head = [x for x in xs if x != int(x)][:_CAP]
    for i, a in enumerate(head):
        for b in head[i + 1 :]:
            ok |= _exact(a + b) | _exact(abs(a - b))
    return ok


def unverified(answer: str, evidence: str, question: str = "") -> list[str]:
    """Identify any numbers in an answer that lack mathematical derivation from evidence.

    Args:
        answer: Model-generated answer text.
        evidence: Ground-truth tool outputs and citations provided to the model.
        question: User inquiry string.

    Returns:
        list[str]: List of unverified or hallucinated numerical tokens.
    """
    text = LIST_MARK.sub(" ", answer)
    ok = allowed(evidence, question)
    seen, out = set(), []
    for n in NUM.findall(text):
        s = numbers(n).pop()
        if (
            s in ok
            or s in seen
            or (len(s) == 4 and s.startswith("20"))
            or s in {"0", "1", "2", "3", "4", "5"}
        ):
            continue
        seen.add(s)
        out.append(s)
    return out
