"""
Where the copilot may take the operator: the dashboard's pages, and the words people use for
them. The rules router, the twin_navigate tool and its guard all read this one table, so a
spoken "show me the oven" and a model's tool call land on the same page, and that page is one
the dashboard really has (web/src/dashboard/Dashboard.tsx, PAGES - the ids below mirror it,
tests/test_navigation.py checks the two agree).

Moving the view changes nothing in the factory, so navigation is not a write: it is checked
(the page must exist) and audited, but never frozen or held for approval.
"""

from __future__ import annotations

import re

# the dashboard's pages: id -> the label its sidebar shows (Dashboard.tsx PAGES)
LABELS = {
    "overview": "Overview",
    "production": "Production",
    "quality": "Quality & trace",
    "vision": "Vision QC",
    "alarms": "Alarms",
    "copilot": "NEXUS",
    "health": "Health",
    "maintenance": "Maintenance",
    "month": "Two months",
    "throughput": "Throughput",
    "process": "Oven process",
    "scheduler": "Learned scheduler",
    "energy": "Energy & grid",
    "carbon": "Carbon per cookie",
    "security": "OT security",
    "hardening": "Defence in depth",
    "engineering": "Engineering",
    "validation": "Validation",
    "data": "Data",
    "docs": "Documentation",
    "docs-degradation": "Hardware degradation",
}
PAGES = frozenset(LABELS)

# the words for a page that are not its id: machine names lead to the page that shows the
# machine, and the old navigation names (warehouse, oven, analytics, twin) keep working
ALIASES = {
    "home": "overview", "dashboard": "overview", "twin": "overview", "3d": "overview",
    "live cell": "overview", "cell": "overview",
    "warehouse": "production", "high bay": "production", "high-bay": "production",
    "hbw": "production", "rack": "production", "crane": "production", "line": "production",
    "orders": "production", "robot": "production", "robot arm": "production",
    "gripper": "production", "vgr": "production",
    "oven": "process", "oven process": "process", "baking": "process", "bake": "process",
    "furnace": "process",
    "trace": "quality", "traceability": "quality", "quality and trace": "quality",
    "camera": "vision", "inspection": "vision", "vision qc": "vision",
    "alarm": "alarms", "alerts": "alarms", "faults": "alarms",
    "nexus": "copilot", "assistant": "copilot", "chat": "copilot",
    "machine health": "health", "condition": "health",
    "service plan": "maintenance", "predictive maintenance": "maintenance",
    "two months": "month", "history": "month",
    "analytics": "throughput", "output": "throughput", "oee": "throughput",
    "schedule": "scheduler", "learned scheduler": "scheduler",
    "grid": "energy", "energy and grid": "energy", "power": "energy", "microgrid": "energy",
    "co2": "carbon", "carbon per cookie": "carbon", "emissions": "carbon",
    "ot security": "security", "cyber security": "security", "cybersecurity": "security",
    "defence in depth": "hardening", "defense in depth": "hardening",
    "documentation": "docs", "manual": "docs", "manuals": "docs",
    "hardware degradation": "docs-degradation", "degradation": "docs-degradation",
}

_WORDS = {**{p: p for p in PAGES}, **{p.replace("-", " "): p for p in PAGES}, **ALIASES}
_NAME = "|".join(re.escape(w) for w in sorted(_WORDS, key=len, reverse=True))
# a request to move the view, and nothing else: "take me to the oven", "open alarms page",
# "show me the camera". "Show me the oven temperature" is a question, not a request to move,
# so the page's name must end the request.
REQUEST = re.compile(
    r"^\s*(?:please\s+|can you\s+|could you\s+)?"
    r"(?:navigate to|take me to|go to|go back to|open(?: up)?|show(?: me)?|bring up"
    r"|switch to|jump to)"
    r"\s+(?:the\s+)?(?P<name>" + _NAME + r")"
    r"(?:\s+(?:page|view|dashboard|tab|screen))?(?:\s+please)?\s*[.!?]*\s*$",
    re.I,
)


def resolve(name: str | None) -> str | None:
    """A page id for a page's id or one of its names, or None for a page the dashboard lacks."""
    if not name or not isinstance(name, str):
        return None
    w = re.sub(r"\s+(page|view|dashboard|tab|screen)$", "", name.strip().lower())
    w = re.sub(r"^the\s+", "", w)
    return _WORDS.get(w) or _WORDS.get(w.replace("_", " "))


def request(text: str) -> str | None:
    """The page a request to move the view asks for ("take me to the oven" -> process), or None
    when the text is not such a request."""
    m = REQUEST.match(text or "")
    return _WORDS[m.group("name").lower()] if m else None
