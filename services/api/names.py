"""
The design-step numbers of the generators (Upgrade 1 ... 18, U1 ... U18) shown as the features
they built - the Python twin of web/src/shared/names.ts, tested against the same cases
(tests/fixtures/names_cases.json), so the chat says what the dashboard says.
"""

from __future__ import annotations

import re
from typing import Any

FEATURE = {
    1: "stiffened structure",
    2: "machine safety",
    3: "remote I/O",
    4: "PLC program",
    5: "commissioning",
    6: "condition monitoring",
    7: "lifecycle design",
    8: "AI maintenance",
    9: "microgrid",
    10: "throughput program",
    11: "OT security",
    12: "hardened machine",
    13: "live PLC",
    14: "connectivity",
    15: "vision QC",
    16: "scheduler",
    17: "copilot",
    18: "carbon model",
}

REF = r"(?:Upgrades?\s|U)"


def _name(n: str) -> str:
    return FEATURE.get(int(n), f"step {n}")


RULES: list[tuple[re.Pattern, Any]] = [
    (re.compile(r"so Upgrade 1 leaves it alone"), "so it stays as it is"),
    (re.compile(r"Upgrade 12 interlock"), "interlock"),
    (
        re.compile(r"U10's slowest run (still )?beats U7's fastest"),
        lambda m: f"the new program's slowest run {m.group(1) or ''}beats the old one's fastest",
    ),
    (re.compile(r"\s*\(" + REF + r"\d{1,2}(?:\s*[-–,]\s*(?:and\s+)?U?\d{1,2})*\)"), ""),
    (re.compile(r"\(" + REF + r"\d{1,2}[:\s]\s*"), "("),
    (re.compile(r"^" + REF + r"\d{1,2}\s*[-–:]\s+"), ""),
    (re.compile(r"\bUpgrade \d{1,2}'s "), "the "),
    (
        re.compile(r"\bUpgrades (\d{1,2}) and (\d{1,2})\b"),
        lambda m: f"{_name(m.group(1))} and {_name(m.group(2))}",
    ),
    (re.compile(r"(?<![-\w.])(?:Upgrade |U)(\d{1,2})(?![-\d])"), lambda m: _name(m.group(1))),
]


def clean(s: str) -> str:
    """One string with its design-step references replaced by feature names."""
    s = re.sub(r"\b(cell|Cell|CELL|stf|STF)-[Uu]12\b", lambda m: f"{m.group(1)}-01", s)
    if len(s) > 64 and not re.search(r"\s", s):
        return s  # ids, URLs, base64
    if not re.search(r"Upgrade|\bU\d", s):
        return s
    out = s
    for rx, to in RULES:
        out = rx.sub(to, out)
    out = re.sub(r"\s{2,}", " ", out)
    out = re.sub(r"\s+([,.;:)])", r"\1", out)
    if out[:1] != s[:1] and out[:1].islower() and s[:1].isupper():
        out = out[0].upper() + out[1:]
    return out


def clean_deep(v: Any) -> Any:
    """Every string value in a parsed JSON document, cleaned; keys are left as they are."""
    if isinstance(v, str):
        return clean(v)
    if isinstance(v, list):
        return [clean_deep(x) for x in v]
    if isinstance(v, dict):
        return {k: clean_deep(x) for k, x in v.items()}
    return v
