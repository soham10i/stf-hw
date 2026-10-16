"""
The copilot's tools: one implementation of every fact the chat can state about the twin.

Each tool is a plain function of its arguments and the request's context (machine age, PM on or
off, the dashboard page), declared with a JSON schema. The same table serves three callers:

  - Gemini and Ollama call them themselves (function calling, chat.py), as many as a question
    needs - "compare the belt and the spindle" is two parts in one call;
  - the rules mode routes a question to them by keyword (route() below), with no model;
  - the evaluation (tests/copilot_eval.json, eval_copilot.py) checks both.

Every result carries its sources and the dashboard page that shows it, so an answer can cite
them and link there. Numbers come only from the twin's exports (web/public) and the documents.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass, field

from . import live
from .grounding import get_bm25, load_json

DOCS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "docs", "assistant"))
MACHINE = "hbw_parts_up12.json"


@dataclass
class Ctx:
    age: float = 140.0  # machine age in shifts (the dashboard's slider)
    pm: bool = True  # preventive maintenance on
    page: str | None = None  # dashboard page id
    client: str = "local"  # whose live twin state to read


@dataclass
class Result:
    tool: str
    text: str
    facts: list[list[str]] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    link: dict[str, str] | None = None

    def as_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v not in (None, [], "")}


def pct(x: float, d: int = 0) -> str:
    return f"{x * 100:.{d}f} %"


# ------------------------------------------------------------------------ health
PART_WORDS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"suction|\bcup\b|vacuum seal", re.I), "cup"),
    (re.compile(r"oven door|door cyl", re.I), "door"),
    (re.compile(r"lowering|sauger", re.I), "lower"),
    (re.compile(r"pusher|auswerfer", re.I), "pusher"),
    (re.compile(r"\bbelt\b|conveyor", re.I), "belt"),
    (re.compile(r"rfid|read head", re.I), "rfid"),
    (re.compile(r"spindle|\bnut\b", re.I), "spindle"),
    (re.compile(r"gearbox|swivel", re.I), "gearbox"),
    (re.compile(r"\bair\b|leak|compressor", re.I), "air"),
    (re.compile(r"colou?r sensor|\ba4\b|\bled\b", re.I), "colour"),
]


def _comp_at(c: dict, shifts: float, pm: bool) -> dict:
    per = c.get("per_shift") or 1.0
    n = shifts * per
    serviced = 0
    warn, fail = c.get("warn"), c.get("fail")
    if pm and warn:
        serviced = int(n // warn)
        n -= serviced * warn
    curve = c.get("curve") or [[0, 0, 100]]
    p = next((pt for pt in curve if pt[0] >= n), curve[-1])
    status = (
        "fail"
        if fail is not None and n >= fail
        else "warn"
        if warn is not None and n >= warn
        else "ok"
    )
    return {
        "c": c,
        "n": n,
        "hi": 0 if status == "fail" else p[2],
        "status": status,
        "serviced": serviced,
        "warn_in": ((warn or 0) - n) / per,
        "fail_in": max(0.0, ((fail or 0) - n) / per),
    }


def machine_health(args: dict, ctx: Ctx) -> Result:
    """Wear parts' health at a machine age: which part needs service first, or the named parts."""
    cad = load_json(MACHINE) or {}
    comps = (cad.get("health") or {}).get("components", [])
    if not comps:
        return Result("machine_health", "The health model is not available.")
    age = float(args.get("age_shifts") or ctx.age)
    pm = ctx.pm if args.get("pm") is None else bool(args["pm"])
    want = [p for p in (args.get("parts") or []) if p]
    states = [_comp_at(c, age, pm) for c in comps if not want or c["id"] in want]
    if not states:
        return Result(
            "machine_health",
            f"No monitored part matches {', '.join(want)}. "
            f"Monitored: {', '.join(c['id'] for c in comps)}.",
        )
    states.sort(key=lambda s: (0 if s["status"] != "ok" else 1, s["warn_in"]))

    def line(s: dict) -> str:
        if s["status"] == "fail":
            return "FAILED - replace it"
        if s["status"] == "warn":
            return f"warned - fails in {s['fail_in']:.1f} shifts"
        hi, w, f = round(s["hi"]), s["warn_in"], s["fail_in"]
        return f"health {hi} - warns in {w:.1f} shifts, fails in {f:.1f}"

    facts = [[s["c"]["name"], line(s)] for s in states[:8]]
    for s in states[:3] if want else []:
        facts.append([f"{s['c']['name']}: measured by", s["c"].get("metric", "")])
    due = [s for s in states if s["status"] != "ok"]
    if want:
        text = "; ".join(f"{s['c']['name']}: {line(s)}" for s in states) + "."
    elif due:
        text = f"{', '.join(s['c']['name'] for s in due)} need service now."
    else:
        nxt = states[0]
        text = f"Nothing is due. Next: {nxt['c']['name']} warns in {nxt['warn_in']:.1f} shifts."
    return Result(
        "machine_health",
        text,
        facts,
        [
            f"condition-monitoring model at machine age {age:g} shifts, preventive maintenance "
            f"{'on' if pm else 'off'}"
        ],
        {
            "page": "maintenance" if not want else "health",
            "label": "Maintenance" if not want else "Health",
        },
    )


# ------------------------------------------------------------------------ alarms
ALARM_RE = re.compile(r"\b([A-Z]{3})-([A-Z]?\d{2})\b", re.I)


def alarm_lookup(args: dict, ctx: Ctx) -> Result:
    """One alarm code's meaning, cause, reaction and recovery; or the codes of a prefix
    (e.g. OVN)."""
    cad = load_json(MACHINE) or {}
    alarms = (cad.get("control") or {}).get("alarms", [])
    code = str(args.get("code", "")).upper().strip()
    hit = next((a for a in alarms if a.get("code") == code), None)
    if hit:
        facts = [[k, str(hit[k])] for k in ("cause", "reaction", "recovery") if hit.get(k)]
        if hit.get("limit"):
            facts.append(["watchdog limit", f"{hit['limit']} s"])
        return Result(
            "alarm_lookup",
            f"{hit['code']}: {hit['text']}.",
            facts,
            [f"PLC alarm list, {hit['code']}"],
            {"page": "alarms", "label": "Alarms"},
        )
    pref = [a for a in alarms if a.get("code", "").startswith(code.split("-")[0])] if code else []
    if pref:
        return Result(
            "alarm_lookup",
            f"{len(pref)} alarms start with {code.split('-')[0]}.",
            [[a["code"], a["text"]] for a in pref[:12]],
            ["PLC alarm list"],
            {"page": "alarms", "label": "Alarms"},
        )
    return Result(
        "alarm_lookup",
        f"There is no alarm {code or 'with that code'}. Codes look like HBW-C01, SYS-04 or "
        "OVN-D02.",
        sources=["PLC alarm list"],
    )


# ------------------------------------------------------------------------ the month
def month_downtime(args: dict, ctx: Ctx) -> Result:
    """The simulated month: why and how often the line stopped, downtime, OEE of the month."""
    m = load_json("month/month.json")
    if not m:
        return Result("month_downtime", "The month simulation is not available.")
    faults = [e for e in m.get("events", []) if e.get("kind") in ("fault", "failure")]
    by: dict[str, list[float]] = {}
    for e in faults:
        k = e.get("code") or e.get("what", "unknown")
        b = by.setdefault(k, [0, 0.0])
        b[0] += 1
        b[1] += float(e.get("lost_s") or e.get("down_h", 0) * 3600)
    top = sorted(by.items(), key=lambda kv: kv[1][1], reverse=True)
    k = m.get("kpi", {})
    text = (
        f"In the simulated month the line stopped {len(faults)} times ({k.get('unplanned_h', 0)} "
        "h unplanned). "
        + (
            f"The biggest cause was {top[0][0]} ({top[0][1][0]} stops, {top[0][1][1] / 60:.0f} "
            "min)."
            if top
            else ""
        )
    )
    facts = [[c, f"{n}x, {s / 60:.1f} min lost"] for c, (n, s) in top[:5]]
    facts += [
        ["month OEE", pct(k.get("oee", 0), 1)],
        ["MTBF", f"{k.get('mtbf_h', 0)} h"],
        ["MTTR", f"{k.get('mttr_min', 0)} min"],
        ["cookies per hour", str(k.get("cookies_per_h", 0))],
    ]
    return Result(
        "month_downtime",
        text,
        facts,
        ["simulated month (month.py)"],
        {"page": "month", "label": "Month"},
    )


# ------------------------------------------------------------------------ OEE
def oee_bottleneck(args: dict, ctx: Ctx) -> Result:
    """Commissioning: order time, OEE in a shift with every fault once, the bottleneck unit."""
    vc = (load_json(MACHINE) or {}).get("vc", {})
    p = vc.get("performance", {})
    if not p:
        return Result("oee_bottleneck", "The commissioning results are not available.")
    parts = sorted(
        (
            ("availability", p["availability"]),
            ("performance", p["performance"]),
            ("quality", p["quality"]),
        ),
        key=lambda x: x[1],
    )
    busy = (p.get("busy") or {}).get(p.get("bottleneck"), None)
    text = (
        f"OEE is {pct(p['oee'], 1)} in a shift that injects every fault once; the largest loss is "
        f"{parts[0][0]} "
        f"({pct(parts[0][1], 1)}). A 12-cookie order takes {p['makespan']} s; the bottleneck is "
        f"the {p['bottleneck']}" + (f" ({busy} s busy of {p['makespan']} s)." if busy else ".")
    )
    facts = [[k, pct(v, 1)] for k, v in parts] + [
        ["order time, commissioned", f"{p['makespan']} s"],
        ["order time, model", f"{p['model']} s"],
        ["bottleneck", str(p["bottleneck"])],
    ]
    for u, s in sorted((p.get("busy") or {}).items(), key=lambda kv: -kv[1])[:4]:
        facts.append([f"busy: {u}", f"{s} s"])
    return Result(
        "oee_bottleneck",
        text,
        facts,
        ["virtual commissioning"],
        {"page": "overview", "label": "Overview"},
    )


# ------------------------------------------------------------------------ energy, carbon
def energy_month(args: dict, ctx: Ctx) -> Result:
    """The microgrid month: consumption, PV and battery share, grid import and cost."""
    g = load_json("grid/grid.json")
    if not g:
        return Result("energy_month", "The energy simulation is not available.")
    sc = g.get("scenarios", {})
    b, o = sc.get("pv+battery", {}), sc.get("grid", {})
    text = (
        f"The cell used {b.get('load_kwh', 0)} kWh in the simulated month; PV and battery covered "
        f"{pct(b.get('self_sufficiency', 0))}, costing €{b.get('total_eur', 0)} against "
        f"€{o.get('total_eur', 0)} on grid power alone."
    )
    facts = [
        ["grid import", f"{b.get('import_kwh', 0)} kWh"],
        ["self-sufficiency", pct(b.get("self_sufficiency", 0))],
        ["cost with PV + battery", f"€{b.get('total_eur', 0)}"],
        ["cost, grid only", f"€{o.get('total_eur', 0)}"],
    ]
    return Result(
        "energy_month",
        text,
        facts,
        ["microgrid month simulation (grid.py)"],
        {"page": "energy", "label": "Energy & grid"},
    )


def carbon_per_cookie(args: dict, ctx: Ctx) -> Result:
    """Grams of CO2e per good cookie, the idle share, and what each lever saves."""
    c = load_json("carbon/carbon.json")
    if not c:
        return Result("carbon_per_cookie", "The carbon model is not available.")
    lev = c.get("levers", {})
    built = lev.get("as built: PV + battery", {}).get("g_per_cookie", 0)
    best = min(lev.items(), key=lambda kv: kv[1].get("g_per_cookie", 1e9)) if lev else ("", {})
    text = (
        f"{built:.3f} g CO2e per good cookie as built; {pct(c.get('standing_share', 0))} of it "
        "comes from the cell "
        f"standing idle. The lowest lever is '{best[0]}' at {best[1].get('g_per_cookie', 0):.3f} g."
    )
    facts = [
        [k, f"{v.get('g_per_cookie', 0):.3f} g" + (" (estimate)" if v.get("estimate") else "")]
        for k, v in lev.items()
    ]
    return Result(
        "carbon_per_cookie",
        text,
        facts[:8],
        ["carbon model (carbon.py) over the microgrid month"],
        {"page": "carbon", "label": "Carbon per cookie"},
    )


# ---------------------------------------------------------------------- scheduler, vision, security
def scheduler_benchmark(args: dict, ctx: Ctx) -> Result:
    """The learned scheduler against the PLC's dispatch policy: order times, wins, deadlocks."""
    s = load_json("sched/rl.json")
    if not s:
        return Result("scheduler_benchmark", "The scheduler benchmark is not available.")
    ev = s.get("eval", {})
    r = ev.get("rollout, no learning", {})
    p = ev.get(s.get("meta", {}).get("fallback", ""), {})
    pr, un = s.get("paired", {}), s.get("unshielded", {})
    text = (
        f"The shielded scheduler finishes an order in {r.get('nominal', 0)} s against the PLC's "
        f"{p.get('nominal', 0)} s, "
        f"faster in {pr.get('wins', 0)} of {pr.get('runs', 0)} paired runs; without the shield an "
        "agent deadlocked in "
        f"{un.get('deadlocks', 0)} of {un.get('episodes', 0)} orders."
    )
    facts = [
        ["scheduler, mean", f"{r.get('mean', 0)} s"],
        ["PLC, mean", f"{p.get('mean', 0)} s"],
        ["saved per order", f"{pr.get('mean_diff_s', 0)} s"],
    ]
    return Result(
        "scheduler_benchmark",
        text,
        facts,
        ["scheduler benchmark (sched_rl.py)"],
        {"page": "scheduler", "label": "Learned scheduler"},
    )


def vision_inspection(args: dict, ctx: Ctx) -> Result:
    """The camera inspection: accuracy, escapes and false rejects, on the line it was trained
    for and after a lighting shift."""
    v = load_json("vision/results.json")
    a = load_json("vision/adapt.json") or {}
    if not v:
        return Result("vision_inspection", "The vision results are not available.")
    i, s = v["results"]["in_domain"], v["results"]["shifted"]
    text = (
        f"On the line it was trained for, the inspection is {pct(i['condition_acc'], 1)} accurate "
        f"with {pct(i['escape_rate'], 1)} escapes. "
        f"After a lighting shift it falls to {pct(s['condition_acc'], 1)} with "
        f"{pct(s['false_reject'], 1)} false rejects. "
        "Label-free adaptation did not fix it - the line's mix of good and bad cookies differs "
        "from training - "
        "so the autoencoder's job is to raise the drift alarm and route doubtful cookies to a "
        "person."
    )
    facts = [
        ["trained line: escapes", pct(i["escape_rate"], 2)],
        ["trained line: false rejects", pct(i["false_reject"], 2)],
        ["shifted: accuracy", pct(s["condition_acc"], 1)],
        ["shifted: false rejects", pct(s["false_reject"], 1)],
    ]
    g = (a.get("guard") or {}).get("source", {})
    if g:
        facts.append(
            [
                "escapes, CNN alone -> with autoencoder",
                f"{pct(g['CNN alone']['escapes'], 1)} -> "
                f"{pct(g['CNN + autoencoder']['escapes'], 1)}",
            ]
        )
    return Result(
        "vision_inspection",
        text,
        facts,
        ["vision benchmark (vision/train.py, vision/adapt.py)"],
        {"page": "vision", "label": "Vision QC"},
    )


def security_attacks(args: dict, ctx: Ctx) -> Result:
    """The OT security design: zones, and each replayed attack's outcome with and without
    protection."""
    d = load_json("security/security.json")
    if not d:
        return Result("security_attacks", "The security assessment is not available.")
    atk = d.get("attacks", [])
    want = str(args.get("attack", "")).lower()
    sel = [
        a
        for a in atk
        if want and (want in a.get("id", "").lower() or want in a.get("name", "").lower())
    ] or atk
    facts = [
        [
            f"{a['id']} {a['name']}",
            f"none: {a.get('without', '')} | protected: {a.get('with', '')}"[:300],
        ]
        for a in sel[:6]
    ]
    zones = "; ".join(f"{z['id']} {z['name']}" for z in d.get("zones", []))
    text = f"{len(atk)} attacks are replayed on the twin; the cell is split into zones {zones}."
    return Result(
        "security_attacks",
        text,
        facts,
        ["OT security assessment (security.py), a model, not a penetration test"],
        {"page": "security", "label": "OT security"},
    )


# ------------------------------------------------------------------------ documents
def search_docs(args: dict, ctx: Ctx) -> Result:
    """The documents (machine, panels, dashboard pages, alarms, FAQ, design notes), best
    passages first."""
    q = str(args.get("query", "")).strip()
    hits = [h for h in get_bm25().search(q, top_k=int(args.get("k") or 4)) if h["score"] >= 2.0]
    if not hits:
        return Result("search_docs", f"No document covers '{q}'.")
    facts, sources = [], []
    for h in hits:
        p = h["passage"]
        where = " > ".join(dict.fromkeys([p.doc, *[x for x in p.path if x]]))
        facts.append([where, p.text[:900]])
        sources.append(where)
    return Result("search_docs", f"{len(hits)} passages match.", facts, sources)


def page_guide(args: dict, ctx: Ctx) -> Result:
    """What a dashboard page shows and how to read it (default: the page the operator is on)."""
    page = re.sub(r"[^a-z0-9-]", "", str(args.get("page") or ctx.page or ""))
    path = os.path.join(DOCS_DIR, f"dashboard-{page}.md")
    if not page or not os.path.exists(path):
        return Result("page_guide", f"There is no guide for the page '{page}'.")
    text = open(path, encoding="utf-8").read()
    title = re.search(r"^#\s+(.+)$", text, re.M)
    body = re.sub(r"\*Generated from.*", "", text).strip()
    return Result(
        "page_guide",
        body[:2800],
        sources=[title.group(1) if title else f"dashboard page {page}"],
        link={"page": page, "label": title.group(1).replace("Dashboard: ", "") if title else page},
    )


# ------------------------------------------------------------------------ live state
def live_state(args: dict, ctx: Ctx) -> Result:
    """What the 3D twin is doing right now: the current order and step, oven temperature,
    sensors, rack."""
    snap, age_s = live.latest(ctx.client)
    if snap is None:
        return Result(
            "live_state",
            "The 3D twin is not open, so there is no live state. Open the twin to see it run.",
        )
    facts = [[k, str(v)] for k, v in snap.items() if not isinstance(v, (dict, list))]
    for k, v in snap.items():
        if isinstance(v, dict):
            facts.append([k, ", ".join(f"{a}: {b}" for a, b in v.items())])
        elif isinstance(v, list):
            facts.append([k, "; ".join(str(x) for x in v[:12])])
    return Result(
        "live_state",
        f"Live state of the twin, {age_s:.0f} s ago.",
        facts[:24],
        [f"the running 3D twin, {age_s:.0f} s ago"],
    )


# ------------------------------------------------------------------------ the table
@dataclass
class Tool:
    name: str
    fn: Callable[[dict, Ctx], Result]
    params: dict


def _obj(props: dict, required: list[str] | None = None) -> dict:
    o = {"type": "object", "properties": props}
    if required:
        o["required"] = required
    return o


PART_IDS = ["cup", "door", "lower", "pusher", "belt", "rfid", "spindle", "gearbox", "air", "colour"]
TOOLS: dict[str, Tool] = {
    t.name: t
    for t in [
        Tool(
            "machine_health",
            machine_health,
            _obj(
                {
                    "parts": {
                        "type": "array",
                        "items": {"type": "string", "enum": PART_IDS},
                        "description": "wear parts to report; empty = all, sorted by what needs "
                        "service first. cup = suction cup seal, "
                        "door = oven door cylinder, lower = oven gripper lowering cylinder, "
                        "pusher = oven pusher cylinder, "
                        "belt = warehouse belt, rfid = RFID heads, spindle = crane travel spindle "
                        "and nut, "
                        "gearbox = robot swivel gearbox, air = air supply leaks, colour = colour "
                        "sensor LED",
                    },
                    "age_shifts": {
                        "type": "number",
                        "description": "machine age in shifts; default: the dashboard's slider",
                    },
                    "pm": {
                        "type": "boolean",
                        "description": "preventive maintenance on; default: the dashboard's switch",
                    },
                }
            ),
        ),
        Tool(
            "alarm_lookup",
            alarm_lookup,
            _obj(
                {
                    "code": {
                        "type": "string",
                        "description": "an alarm code like HBW-C01, SYS-04, OVN-D02, "
                        "or a prefix like OVN",
                    }
                },
                ["code"],
            ),
        ),
        Tool("month_downtime", month_downtime, _obj({})),
        Tool("oee_bottleneck", oee_bottleneck, _obj({})),
        Tool("energy_month", energy_month, _obj({})),
        Tool("carbon_per_cookie", carbon_per_cookie, _obj({})),
        Tool("scheduler_benchmark", scheduler_benchmark, _obj({})),
        Tool("vision_inspection", vision_inspection, _obj({})),
        Tool(
            "security_attacks",
            security_attacks,
            _obj(
                {
                    "attack": {
                        "type": "string",
                        "description": "an attack id (A1...) or a word of its name; empty = all",
                    }
                }
            ),
        ),
        Tool(
            "search_docs",
            search_docs,
            _obj(
                {
                    "query": {
                        "type": "string",
                        "description": "what to look up, in a few keywords",
                    },
                    "k": {"type": "integer", "description": "passages to return, 1-6"},
                },
                ["query"],
            ),
        ),
        Tool(
            "page_guide",
            page_guide,
            _obj(
                {
                    "page": {
                        "type": "string",
                        "description": "dashboard page id; default: the operator's page",
                    }
                }
            ),
        ),
        Tool("live_state", live_state, _obj({})),
    ]
}


def declarations() -> list[dict]:
    """The tools as function declarations (the same JSON schema for Gemini and Ollama)."""
    return [
        {"name": t.name, "description": (t.fn.__doc__ or "").strip(), "parameters": t.params}
        for t in TOOLS.values()
    ]


def call(name: str, args: dict | None, ctx: Ctx) -> Result:
    t = TOOLS.get(name)
    if not t:
        return Result(name, f"There is no tool '{name}'.")
    try:
        return t.fn(dict(args or {}), ctx)
    except Exception as e:  # a tool must never take the chat down
        return Result(name, f"The tool failed: {type(e).__name__}.")


# ------------------------------------------------------------------ rules: a question -> tool calls
GREETING = re.compile(
    r"^(hi|hello|hey|howdy|greetings|good\s+(morning|afternoon|evening))\b[\s!.,?]*$", re.I
)


def route(q: str, ctx: Ctx) -> list[tuple[str, dict]]:
    """The tool calls a question needs, by keyword - the rules mode, and the facts every model
    starts from. Several calls when a question asks several things."""
    s = q.lower()
    calls: list[tuple[str, dict]] = []
    codes = [f"{a}-{b}".upper() for a, b in ALARM_RE.findall(q)]
    for c in codes:
        calls.append(("alarm_lookup", {"code": c}))
    parts = list(dict.fromkeys(pid for rx, pid in PART_WORDS if rx.search(s)))
    healthy = re.search(
        r"\b(fail|life|last|health|worn|wear|rul|how long|when|replace|service|maint)", s
    )
    if parts and healthy:
        calls.append(("machine_health", {"parts": parts}))
    elif re.search(
        r"service|maintain|maintenance|replace|renew|work order|needs? attention|due", s
    ):
        calls.append(("machine_health", {}))
    if re.search(
        r"\b(right )?now\b|currently|at the moment|is the oven (hot|on)|which cookie"
        r"|what is (it|the cell|the machine) doing|live",
        s,
    ):
        calls.append(("live_state", {}))
    if re.search(
        r"this month|downtime|why did .* stop|stopped|mtbf|mttr|how often", s
    ) and not re.search(r"e-?stop|emergency", s):
        calls.append(("month_downtime", {}))
    if re.search(
        r"\boee\b|bottleneck|order time|makespan|availability|throughput|cookies per hour"
        r"|long does an order|order take",
        s,
    ):
        calls.append(("oee_bottleneck", {}))
    if re.search(r"co2|carbon|emission|footprint|grams? per", s):
        calls.append(("carbon_per_cookie", {}))
    elif re.search(r"energy|kwh|solar|\bpv\b|battery|grid|electricity|power bill", s):
        calls.append(("energy_month", {}))
    if re.search(r"schedul|dispatch|deadlock|reinforcement|\brl\b", s):
        calls.append(("scheduler_benchmark", {}))
    if re.search(
        r"vision|camera|inspection|\bcnn\b|defect|escape|false reject|chipped|cracked|burnt", s
    ):
        calls.append(("vision_inspection", {}))
    if re.search(
        r"secur|attack|hack|cyber|firewall|malware|spoof|write coils?|modbus write|62443", s
    ):
        calls.append(("security_attacks", {}))
    if re.search(r"this page|on this page|what (does|is) (this|the) page|how (do i|to) read", s):
        calls.append(("page_guide", {}))
    if not calls or re.search(r"\bhow does\b|\bwhy\b|\bwhat is\b|\bexplain\b|circuit|works?\b", s):
        calls.append(("search_docs", {"query": q}))
    return calls


def _gist(guide: str) -> str:
    body = re.sub(r"^#.*\n|Dashboard group:.*\n", "", guide).strip()
    what = body.split("\n\n")[0]
    steps = re.search(r"## How to read it\s+(.+?)(\n\n##|$)", body, re.S)
    read = (
        " ".join(re.sub(r"^\d+\.\s*", "", x) for x in steps.group(1).strip().split("\n"))
        if steps
        else ""
    )
    return (what + (" How to read it: " + read if read else ""))[:600]


def rules_answer(q: str, ctx: Ctx) -> tuple[str, list[Result]]:
    """The no-model answer: the routed tools' texts, or the best passage."""
    if GREETING.match(q.strip()):
        return (
            "Hello! I am the twin's copilot. Ask about machine health and maintenance, alarm "
            "codes, OEE and "
            "bottlenecks, downtime, energy and carbon, the scheduler, vision inspection, "
            "security, or what the cell "
            "is doing right now."
        ), []
    res = [call(n, a, ctx) for n, a in route(q, ctx)]
    # a page guide is long: the rules answer gives its gist (what the page is for, how to read it)
    texts = [
        _gist(r.text) if r.tool == "page_guide" else r.text for r in res if r.tool != "search_docs"
    ]
    if not texts:
        # quote a passage only when it really matches (most of the question's words, a clear score)
        top = get_bm25().search(q, top_k=1)
        docs = next((r for r in res if r.tool == "search_docs" and r.facts), None)
        strong = top and top[0]["score"] >= 4.0 and top[0]["cover"] > 0.5
        texts = (
            [f"{docs.facts[0][1][:420]}… [{docs.facts[0][0]}]"]
            if docs and strong
            else ["I don't know: nothing in the twin's data or documents covers that."]
        )
    return " ".join(texts), res
