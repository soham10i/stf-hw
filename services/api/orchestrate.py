"""
The orchestrator: for each question, which kind of answer it needs - decided here, on the
server, by rules anyone can read, before any model is asked. A model never decides on its own to
spend a web search; the route and the reasons for it are returned with the answer.

  chat   a greeting or small talk: the model alone, no retrieval
  twin   the twin's own numbers (health, alarms, OEE, energy, live state): its tools compute
         them, the documents explain them
  docs   how this project works: the knowledge base (BM25 over docs/), quoted with file and line
  web    the outside world - a standard, a vendor, a price, anything recent - that the documents
         cannot hold: one web search, every claim linked to the page it came from
  deep   a research question: it is split into sub-questions, each searched, and the findings
         are written up together with the documents' passages

The signals, in the order they are weighed:

  1. the operator's choice (Auto, Docs, Web, Deep in the composer) - always wins;
  2. a greeting -> chat;
  3. an explicit request: "deep research", "survey", "compare sources" -> deep; "search the web",
     "latest", "news", a recent year -> web;
  4. the twin's own data: a tool the rules router called for this question -> twin;
  5. the documents' match: the best passage's BM25 score and the share of the question's words
     it contains - a strong match -> docs;
  6. outside knowledge: a standard (ISO 13849, IEC 62443), a vendor, or a general-engineering
     question the documents match only weakly -> web, unless the question is about this twin
     (its parts, pages, PLC), which no web page can answer.

Web and deep need a search provider (Groq's browser search, Gemini's Google Search); without
one the question is answered from the documents and the answer says so.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .grounding import get_bm25
from .logging_config import get_logger

logger = get_logger(__name__)

MODES = ("chat", "twin", "docs", "web", "deep")
STRONG_SCORE = 6.0  # a BM25 score this high, with...
STRONG_COVER = 0.5  # ...this share of the question's words, means the documents cover it
VERY_STRONG = (12.0, 0.75)  # so strong that the documents win even for an outside topic

GREETING = re.compile(
    r"^(hi|hello|hey|howdy|thanks|thank you|greetings|good\s+(morning|afternoon|evening))\b"
    r"[\s!.,?]*$",
    re.I,
)
DEEP = re.compile(
    r"\bdeep(ly)?\s+(research|dive|search)|\bresearch\b.{0,40}\b(this|it|on|into|about)\b|"
    r"\bliterature\b|\bsurvey\b|state of the art|\bcompare\b.{0,40}\b(sources|vendors|standards|"
    r"approaches|papers|methods)\b|in[- ]depth (review|analysis|comparison)",
    re.I,
)
WEB = re.compile(
    r"search (the )?(web|internet|online)|\bon the (web|internet)\b|\bonline\b|\bgoogle\b|"
    r"\blatest\b|\bnewest\b|\brecent(ly)?\b|\bnews\b|\btoday\b|\bthis (year|month|week)\b|"
    r"\b20[2-3]\d\b|\bprice\b|\bcost of\b|\bbuy\b|\bwhere (can|do) i (get|buy|find)\b|"
    r"\bweather\b|\bforecast for\b|\bstock market\b",
    re.I,
)
EXTERNAL = re.compile(
    r"\b(iso|iec|en|din|ieee|nist|vdi|vde|ul|ansi|nfpa|osha)\s?-?\d{2,6}|\b(standard|regulation|"
    r"directive|norm|certif\w*|datasheet|vendor|manufacturer|supplier|industry|market)\b|"
    r"\b(siemens|beckhoff|festo|sick|pilz|keyence|rockwell|allen[- ]bradley|omron|schneider|abb|"
    r"fanuc|kuka|mitsubishi|bosch rexroth|codesys|openai|nvidia)\b|"
    r"\bin general\b|\bgenerally\b|\btypical(ly)?\b|\bin (real|other) (factories|plants|industry)",
    re.I,
)
TWIN = re.compile(
    r"\b(this|the|our|my) (twin|cell|factory|machine|line|dashboard|page|model|plc|program|robot|"
    r"oven|warehouse|crane|camera|copilot)\b|\b(stf|hbw|vgr|lagerstelle|drehtisch|sauger|"
    r"auswerfer|cookie|mould|rack|bay|slot|here|in this project)\b|\b[A-Z]{3}-[A-Z]?\d{2}\b",
    re.I,
)
EXPLAIN = re.compile(
    r"\bhow (does|do|is|are|it)\b|\bwhy\b|\bexplain|\bmath|\bformula|\bequation|\bcalculat|"
    r"\bcomput(e|ed|ation)\b|\bderiv|\btheory\b|\bworks?\b",
    re.I,
)
# the tools that compute this twin's own numbers (search_docs and page_guide only retrieve)
DATA_TOOLS = {
    "machine_health",
    "alarm_lookup",
    "month_downtime",
    "oee_bottleneck",
    "energy_month",
    "carbon_per_cookie",
    "scheduler_benchmark",
    "vision_inspection",
    "oven_process",
    "security_attacks",
    "live_state",
    "copilot_setup",
}


@dataclass
class Plan:
    """Orchestration routing plan describing the response strategy and reasoning."""

    mode: str
    why: list[str]
    signals: dict = field(default_factory=dict)
    web: bool = False  # True when a web search will execute (web or deep modes)

    def as_dict(self) -> dict:
        """Convert orchestration plan to a serializable dictionary."""
        return {"mode": self.mode, "why": self.why, "signals": self.signals}


def decide(
    question: str, called: list[str], choice: str | None = None, can_search: bool = True
) -> Plan:
    """Determine the optimal routing strategy for a user query based on heuristic signals.

    Evaluation precedence:
      1. Operator explicit override (docs, web, deep).
      2. Greetings and conversational pleasantries -> chat mode.
      3. Explicit research or web requests -> deep or web mode.
      4. Machine runtime/operational inquiries matching twin data tools -> twin mode.
      5. High lexical BM25 match against knowledge base -> docs mode.
      6. External standards, vendors, or general industrial topics -> web mode.

    Args:
        question: User query string.
        called: List of tool names called by the rules router.
        choice: Optional operator override ('docs', 'web', 'deep').
        can_search: Whether an external search provider is configured.

    Returns:
        Plan: Orchestration decision containing selected mode, rationale, and signal flags.
    """
    q = question.strip()
    try:
        hits = get_bm25().search(q, top_k=1)
    except Exception as e:
        logger.warning("BM25 lexical search failed in router for query %r: %s", q[:50], e)
        hits = []
    score = round(float(hits[0]["score"]), 2) if hits else 0.0
    cover = round(float(hits[0]["cover"]), 2) if hits else 0.0
    data = [t for t in called if t in DATA_TOOLS]
    sig = {
        "doc_score": score,
        "doc_cover": cover,
        "data_tools": data,
        "about_twin": bool(TWIN.search(q)),
        "external": bool(EXTERNAL.search(q)),
        "explicit_web": bool(WEB.search(q)),
        "explicit_deep": bool(DEEP.search(q)),
        "search_provider": can_search,
    }
    strong = score >= STRONG_SCORE and (cover >= STRONG_COVER or score >= 2 * STRONG_SCORE)
    very_strong = score >= VERY_STRONG[0] and cover >= VERY_STRONG[1]
    match = f"the documents' best passage scores {score:g} and holds {cover:.0%} of its words"

    def web_or_docs(mode: str, why: list[str]) -> Plan:
        if can_search:
            return Plan(mode, why, sig, web=True)
        return Plan("docs", [*why, "no web search provider is configured: the documents only"], sig)

    plan: Plan
    if choice in ("docs", "web", "deep"):
        if choice == "docs":
            plan = Plan("docs", ["you chose Docs: the knowledge base only, no web"], sig)
        else:
            plan = web_or_docs(choice, [f"you chose {choice.capitalize()}"])
    elif GREETING.match(q):
        plan = Plan("chat", ["a greeting: no retrieval needed"], sig)
    elif sig["explicit_deep"]:
        plan = web_or_docs("deep", ["the question asks for research across sources"])
    elif sig["explicit_web"]:
        plan = web_or_docs("web", ["the question asks for something recent or on the web"])
    else:
        tools = ", ".join(t.replace("_", " ") for t in data)
        if data and EXPLAIN.search(q) and score >= STRONG_SCORE:
            plan = Plan(
                "docs",
                [
                    f"asks how it works: the documents first ({match}); the twin's numbers "
                    f"({tools}) as the example"
                ],
                sig,
            )
        elif data:
            plan = Plan("twin", [f"the twin's own data: {tools}", match], sig)
        elif sig["external"] and not sig["about_twin"] and not very_strong:
            plan = web_or_docs(
                "web", ["outside knowledge (a standard, a vendor or general practice)", match]
            )
        elif strong:
            plan = Plan("docs", [f"the documents cover it: {match}"], sig)
        elif sig["about_twin"] or score >= STRONG_SCORE / 2:
            plan = Plan("docs", [f"about this twin: {match}"], sig)
        else:
            plan = web_or_docs("web", [f"the documents hardly match: {match}"])

    logger.debug("Orchestration route decided: question=%r -> mode=%s (why=%s)", q[:50], plan.mode, plan.why)
    return plan
