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

import html
import ipaddress
import os
import re
import socket
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import asdict, dataclass, field

from . import gemini_pool as GP
from . import live
from . import security as sec
from .grounding import get_bm25, load_json
from .logging_config import get_logger

logger = get_logger(__name__)

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
    # where each source is, exactly: label (as in sources), file, line, anchor, score, quote
    cites: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v not in (None, [], "")}

    def as_markdown(self) -> str:
        """The result as a model reads it: a Markdown section - the tool's answer, its facts as a
        table, a document passage as a quote under its source and exact place, its sources."""
        out = [f"### Tool `{self.tool}`", "", self.text]
        if self.tool == "search_docs":
            where = {c["label"]: c for c in self.cites}
            for label, text in self.facts:
                c = where.get(label, {})
                at = f"*{c['file']}, line {c['line']}*" if c.get("file") else ""
                out += ["", f"#### [{label}]", at, "", "> " + str(text).replace("\n", " ")]
        elif self.facts:
            out += ["", "| Fact | Value |", "|---|---|"]
            out += [f"| {_md_cell(k)} | {_md_cell(v)} |" for k, v in self.facts]
        if self.sources:
            out += ["", "Sources: " + "; ".join(f"[{x}]" for x in self.sources)]
        if self.link:
            out += [f"Dashboard page: {self.link.get('label', self.link.get('page', ''))}"]
        return "\n".join(x for x in out if x is not None).strip()


def _md_cell(v: object) -> str:
    return str(v).replace("|", "\\|").replace("\n", " ")


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
    ov = g.get("oven_supply", {})
    oven = ov.get("oven", {})
    text = (
        f"The site used {b.get('load_kwh', 0)} kWh in the simulated month; PV and battery covered "
        f"{pct(b.get('self_sufficiency', 0))}, costing €{b.get('total_eur', 0)} against "
        f"€{o.get('total_eur', 0)} on grid power alone."
    )
    if oven:
        text += (
            f" The oven, held at 180 C through both shifts on its own 230 V circuit, is "
            f"{oven.get('month_kwh', 0)} kWh of it ({pct(oven.get('share_of_load', 0))}); "
            "the cell alone uses "
            f"{ov.get('cell_only', {}).get('load_kwh', 0)} kWh."
        )
    facts = [
        ["grid import", f"{b.get('import_kwh', 0)} kWh"],
        ["self-sufficiency", pct(b.get("self_sufficiency", 0))],
        ["cost with PV + battery", f"€{b.get('total_eur', 0)}"],
        ["cost, grid only", f"€{o.get('total_eur', 0)}"],
        [
            "demand response met",
            "yes" if b.get("dr_met") else f"no ({b.get('dr_import_wh', 0)} Wh over)",
        ],
    ]
    for opt in ov.get("options", [])[1:]:
        facts.append(
            [
                "resized microgrid (oven on the UPS)",
                f"€{opt.get('capex_total')}, {opt.get('payback_years')} years payback, "
                f"self-sufficiency {pct(opt.get('kpi', {}).get('self_sufficiency', 0))}",
            ]
        )
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
        f"{built:.3f} g CO2e per good cookie as built; "
        f"{pct(c.get('meta', {}).get('oven_share', 0))} of it "
        f"is the oven held at 180 C and {pct(c.get('standing_share', 0))} the cell standing idle. "
        f"The lowest lever is '{best[0]}' at {best[1].get('g_per_cookie', 0):.3f} g."
    )
    rb = c.get("real_bake")
    if rb:
        text += (
            f" With a real 10-minute bake the oven caps the cell at {rb['cookies_h']} "
            "cookies an hour, "
            f"about {rb['g_per_cookie']:.1f} g a cookie (an estimate)."
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
    """The camera inspection on the process: where the camera is, what the models decide, how
    one damaged cookie in every 12 is caught (QC testing), and ten sample photos' verdicts."""
    sm = load_json("vision/samples/samples.json")
    cam = load_json("vision/camera.json") or {}
    if not sm:
        return Result("vision_inspection", "The vision samples are not available.")
    S = sm["samples"]
    right = sum((x["truth"] == "ok") == (x["verdict"] == "pass") for x in S)
    bad = [x for x in S if x["truth"] != "ok"]
    caught = sum(x["verdict"] != "pass" for x in bad)
    text = (
        f"The camera in the colour hood photographs every cookie; the CNN decides pass, reject or "
        f"'to a person', and a rejected cookie is held at the end of the line and made again. In "
        f"every 12 cookies one is damaged on purpose (QC testing). Of {len(S)} sample photos from "
        f"the process, {right} were decided right, and {caught} of {len(bad)} damaged "
        f"{'cookie was' if len(bad) == 1 else 'cookies were'} caught."
    )
    facts = [
        [
            f"sample {x['n']}: {x['flavour']}",
            f"truth {x['truth']}, CNN {x['condition']} -> {x['verdict']}",
        ]
        for x in S
    ]
    if cam:
        facts.append(
            [
                "camera",
                f"{cam.get('fov_mm', 0):.0f} mm field, in the colour hood before the colour sensor",
            ]
        )
    facts.append(
        ["QC testing", "one cookie in every 12, drawn at random, burnt, underbaked or cracked"]
    )
    return Result(
        "vision_inspection",
        text,
        facts[:12],
        ["the inspection camera's photos of the 3D twin's cookies (vision/samples)"],
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


# ------------------------------------------------------------------------ the bake as a process
def oven_process(args: dict, ctx: Ctx) -> Result:
    """The bake as a process (Upgrade 19): how the oven heats and holds, how long a real bake
    takes, how many cookies come out right with each way of ending a bake, what a real bake does
    to capacity, and the heat per cookie."""
    d = load_json("bake/process.json")
    if not d:
        return Result("oven_process", "The oven process model is not available (make bake).")
    pol = d["policies"]
    best, timer = pol[-1], pol[0]
    demo, real = d["throughput"]["rows"]
    h, e = d["heatup"], d["energy"]
    facts = [
        [
            f"right first time: {p['name']}",
            f"{p['ok_pct']} % ({p['underbaked']} underbaked, {p['burnt']} burnt "
            f"of {p['cookies']}; fridge dough {p['ok_pct_fridge']} %)",
        ]
        for p in pol
    ]
    facts += [
        ["bake time (best policy)", f"{best['bake_mean']:.0f} s ± {best['bake_sd']:.0f} s"],
        [
            "cookies an hour",
            f"{real['cookies_h']} with a real bake, {demo['cookies_h']} with the 2 s lamp",
        ],
        [
            "one oven's limit",
            f"{d['throughput']['oven_limit_h']} cookies an hour; the cell could feed "
            f"{d['throughput']['ovens_to_match']} ovens",
        ],
        ["heat-up to 180 C", f"{h['t180']:.0f} s; holding 180 C takes {h['hold_w']:.0f} W"],
        [
            "heat per cookie",
            f"{e['wh_per_cookie']:.0f} Wh; about {e['oven_month_kwh']} kWh a month on two shifts",
        ],
    ]
    text = (
        f"With a real bake (about {best['bake_mean'] / 60:.0f} min at 180 C) the oven makes "
        f"{real['cookies_h']} cookies an hour against {demo['cookies_h']} with the 2 s lamp. "
        f"A fixed timer gets {timer['ok_pct']} % of cookies right; {best['name']} gets "
        f"{best['ok_pct']} %."
    )
    return Result(
        "oven_process",
        text,
        facts,
        ["the bake-as-a-process model (Upgrade 19, stf-cad/hbw/bake.py), simulated"],
        {"page": "process", "label": "Oven process"},
    )


# ------------------------------------------------------------------------ documents
def search_docs(args: dict, ctx: Ctx) -> Result:
    """The documents (machine, panels, dashboard pages, alarms, FAQ, design notes), best
    passages first."""
    q = str(args.get("query", "")).strip()
    hits = [h for h in get_bm25().search(q, top_k=int(args.get("k") or 4)) if h["score"] >= 2.0]
    if not hits:
        return Result("search_docs", f"No document covers '{q}'.")
    facts, sources, cites = [], [], []
    for h in hits:
        p = h["passage"]
        where = " > ".join(dict.fromkeys([p.doc, *[x for x in p.path if x]]))
        facts.append([where, p.text[: 1400 if "$" in p.text else 900]])
        sources.append(where)
        cites.append(
            {
                "label": where,
                "file": p.file,
                "line": p.line,
                "anchor": p.anchor,
                "score": round(float(h["score"]), 2),
                "quote": p.text[:400],
            }
        )
    return Result("search_docs", f"{len(hits)} passages match.", facts, sources, cites=cites)


def equations(top: Result, budget: int = 7000) -> Result:
    """For a question about the mathematics: the best-matching document's passages that hold
    equations, in the document's order, added to the search's own - so the model is given the
    whole chain (signal, law, smoothing, index, warnings), not only the passages that share the
    question's words."""
    if not top.cites:
        return top
    file = top.cites[0].get("file")
    have = {c["label"] for c in top.cites}
    rows = sorted(
        (p for p in get_bm25().passages if p.file == file and "$$" in p.text),
        key=lambda p: p.line,
    )
    facts, cites, used = list(top.facts), list(top.cites), 0
    for p in rows:
        where = " > ".join(dict.fromkeys([p.doc, *[x for x in p.path if x]]))
        if where in have or used + len(p.text) > budget:
            continue
        used += len(p.text)
        have.add(where)
        facts.append([where, p.text[:1400]])
        cites.append(
            {
                "label": where,
                "file": p.file,
                "line": p.line,
                "anchor": p.anchor,
                "score": 0.0,
                "quote": p.text[:400],
            }
        )
    return Result(
        top.tool, f"{len(facts)} passages match.", facts, [f[0] for f in facts], cites=cites
    )


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


SETUP_PREFIXES = (
    "GEMINI_",
    "GROQ_",
    "GROK_",
    "XAI_",
    "OLLAMA_",
    "TTS_",
    "ELEVENLABS_",
    "STF_",
    "SUPABASE_",
    "UPB_",
)


def _env() -> dict[str, str]:
    """The repo's .env (git-ignored) merged under the process environment, which wins."""
    env: dict[str, str] = {}
    path = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
    try:
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            k, sep, v = line.partition("=")
            if sep and k.strip().startswith(SETUP_PREFIXES):
                env[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    env.update(os.environ)
    return env


def copilot_setup(args: dict, ctx: Ctx) -> Result:
    """How this copilot itself is set up: local text model, Groq LPU engine, Gemini chat
    and speech models in fallback order, speech pipeline, and data directory."""
    from . import tts as tts_mod  # local import: tts imports chat, chat imports this module

    env = _env()
    repo = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    chat = GP.models_from_env("GEMINI_MODELS", GP.CHAT, env)
    first = env.get("GEMINI_MODEL", GP.CHAT[0])
    chat_order = [first, *[m for m in chat if m != first]]
    tts = GP.models_from_env("GEMINI_TTS_MODELS", GP.TTS, env)
    stt = GP.models_from_env("GEMINI_STT_MODELS", tts_mod.STT_MODELS, env)
    providers = [
        p.strip() for p in env.get("TTS_PROVIDERS", "elevenlabs,groq,gemini,local").split(",")
    ]
    providers = [p for p in providers if p]
    groq_set = bool(env.get("GROQ_API_KEY") or env.get("GROK_API_KEY"))
    supabase_set = bool(
        env.get("SUPABASE_URL")
        and (env.get("SUPABASE_SERVICE_KEY") or env.get("SUPABASE_SECRET_KEY"))
    )
    facts = [
        ["Groq API key", "set" if groq_set else "not set"],
        ["Groq text model", env.get("GROQ_MODEL", "qwen/qwen3.8-27b")],
        ["Groq STT model", env.get("GROQ_STT_MODEL", "whisper-large-v3-turbo")],
        ["local text model (Ollama)", env.get("OLLAMA_MODEL", "qwen2.5:7b-instruct")],
        ["Ollama URL", env.get("OLLAMA_URL", "http://127.0.0.1:11434")],
        ["Gemini chat models, fallback order", " -> ".join(chat_order)],
        ["Gemini TTS voices, fallback order", " -> ".join(tts)],
        ["Gemini STT models, fallback order", " -> ".join(stt)],
        ["TTS providers, in order", ", ".join(providers)],
        ["Gemini API key", "set" if env.get("GEMINI_API_KEY") else "not set"],
        ["chat questions per day", env.get("GEMINI_DAILY_LIMIT", "300")],
        ["spoken answers per day", env.get("GEMINI_TTS_DAILY_LIMIT", "100")],
        ["Supabase cloud store", "configured" if supabase_set else "local SQLite"],
        ["data directory", env.get("STF_DATA_DIR", os.path.join(repo, ".data"))],
    ]
    groq_desc = (
        f"Groq LPU acceleration is active ('{facts[1][1]}', STT '{facts[2][1]}'). "
        if groq_set
        else ""
    )
    text = (
        f"{groq_desc}Local text generation runs '{facts[3][1]}' on Ollama at {facts[4][1]}; "
        f"the copilot switches to it when every cloud model is at its limit. Gemini answers in "
        f"fallback order {', '.join(chat_order)}. Speech comes from {', '.join(providers)} "
        f"(Gemini voices: {', '.join(tts)}; STT: {', '.join(stt)})."
    )
    return Result("copilot_setup", text, facts, ["the copilot's own configuration (.env)"])


# ------------------------------------------------------------------------ verified web access
PAGE_LIMITER = sec.RateLimiter(rate=0.2, burst=3)
PAGE_TIMEOUT_S = 8
PAGE_MAX_BYTES = 512_000
_PRIVATE_NETS = [
    ipaddress.ip_network(c)
    for c in (
        "127.0.0.0/8",
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "169.254.0.0/16",
        "::1/128",
        "fc00::/7",
        "fe80::/10",
    )
]


def _public_host(host: str) -> bool:
    """True when every address the host resolves to is a public (routable) one."""
    host = host.lower().rstrip(".")
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".internal"):
        return False
    try:
        addrs = socket.getaddrinfo(host, None)
    except OSError:
        return False
    for info in addrs:
        raw = info[4][0].split("%")[0]
        try:
            ip = ipaddress.ip_address(raw)
        except ValueError:
            return False
        if any(ip in net for net in _PRIVATE_NETS):
            return False
    return bool(addrs)


def _http_get(url: str) -> tuple[bytes, str]:
    req = urllib.request.Request(
        url, method="GET", headers={"User-Agent": "stf-copilot/1.0 (research; contact local)"}
    )
    with urllib.request.urlopen(req, timeout=PAGE_TIMEOUT_S) as r:  # noqa: S310 - SSRF-guarded
        return r.read(PAGE_MAX_BYTES + 1), r.headers.get("Content-Type", "")


def _html_to_text(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", raw)
    raw = re.sub(r"(?is)<!--.*?-->", " ", raw)
    raw = re.sub(r"(?s)<[^>]+>", " ", raw)
    return re.sub(r"\s+", " ", html.unescape(raw)).strip()


def open_page(args: dict, ctx: Ctx) -> Result:
    """Read a public web page (http/https only, no private or local addresses) and quote its
    main text - the verified web access the model uses when the documents do not cover a
    question."""
    url = str(args.get("url", "")).strip()
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return Result("open_page", f"'{url or 'that'}' is not a fetchable http(s) URL.")
    if not _public_host(parsed.hostname):
        return Result(
            "open_page",
            f"'{parsed.hostname}' is a private, local or unknown host; only public web pages "
            "can be fetched.",
        )
    if not PAGE_LIMITER.allow(ctx.client or "?"):
        return Result("open_page", "Too many page fetches; wait a few seconds and try again.")
    try:
        body, ctype = _http_get(url)
    except Exception as e:
        return Result("open_page", f"The page could not be fetched: {type(e).__name__}.")
    if "html" in ctype.lower():
        text = _html_to_text(body.decode("utf-8", "replace"))
    else:
        text = re.sub(r"\s+", " ", body.decode("utf-8", "replace")).strip()
    excerpt = text[:4000]
    where = f"{parsed.hostname}{parsed.path or '/'}"
    return Result(
        "open_page",
        f"Fetched {where}: {excerpt[:300]}" + ("…" if len(excerpt) > 300 else ""),
        [["excerpt", excerpt]],
        [url],
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
        Tool("oven_process", oven_process, _obj({})),
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
        Tool("copilot_setup", copilot_setup, _obj({})),
        Tool(
            "open_page",
            open_page,
            _obj(
                {
                    "url": {
                        "type": "string",
                        "description": "the http(s) URL of a public web page to read and quote",
                    }
                },
                ["url"],
            ),
        ),
    ]
}


def declarations() -> list[dict]:
    """The tools as function declarations (the same JSON schema for Gemini and Ollama)."""
    return [
        {"name": t.name, "description": (t.fn.__doc__ or "").strip(), "parameters": t.params}
        for t in TOOLS.values()
    ]


def call(name: str, args: dict | None, ctx: Ctx) -> Result:
    """Execute a registered copilot tool by name with provided arguments and context.

    Args:
        name: Registered tool name.
        args: Dictionary of tool argument parameters.
        ctx: Execution context containing machine age, PM state, client host, and active page.

    Returns:
        Result: Tool execution result containing text, structured facts, sources, and cites.
    """
    t = TOOLS.get(name)
    if not t:
        logger.warning("Tool not found: '%s'", name)
        return Result(name, f"There is no tool '{name}'.")
    try:
        return t.fn(dict(args or {}), ctx)
    except Exception as e:
        logger.error("Tool '%s' failed execution with args %s: %s", name, args, e, exc_info=True)
        return Result(name, f"The tool failed: {type(e).__name__}.")


# ------------------------------------------------------------------ rules: a question -> tool calls
GREETING = re.compile(
    r"^(hi|hello|hey|howdy|greetings|good\s+(morning|afternoon|evening))\b[\s!.,?]*$", re.I
)


def route(q: str, ctx: Ctx, lean: bool = False) -> list[tuple[str, dict]]:
    """The tool calls a question needs, by keyword - the rules mode, and the facts every model
    starts from. Several calls when a question asks several things. `lean` shrinks the document
    search for small local models."""
    s = q.lower()
    calls: list[tuple[str, dict]] = []
    codes = [f"{a}-{b}".upper() for a, b in ALARM_RE.findall(q)]
    for c in codes:
        calls.append(("alarm_lookup", {"code": c}))
    if re.search(
        r"(which|what) (setup|model)|local model|gemini model|ollama|"
        r"\btts\b|text[- ]?to[- ]?speech|\bstt\b|speech[- ]?to[- ]?text|"
        r"voice (model|pipeline|setup)|copilot.{0,24}(setup|config|model)|"
        r"how (are|is) (you|the copilot) (set ?up|configured)",
        s,
    ) and not re.search(r"\b(plc|oven|machine|robot|crane|camera|servo|motor|sensor)\b", s):
        calls.append(("copilot_setup", {}))
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
        r"\bbak(e|es|ing|ed)\b|oven (temperature|process|energy|heat)|underbak|soft sensor|"
        r"heat per cookie|preheat|how long .{0,20}(bake|in the oven)|browning|dough",
        s,
    ):
        calls.append(("oven_process", {}))
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
        calls.append(("search_docs", {"query": q, "k": 2 if lean else 4}))
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


def rules_answer(q: str, ctx: Ctx, lean: bool = False) -> tuple[str, list[Result]]:
    """The no-model answer: the routed tools' texts, or the best passage."""
    if GREETING.match(q.strip()):
        return (
            "Hello! I am the twin's copilot. Ask about machine health and maintenance, alarm "
            "codes, OEE and "
            "bottlenecks, downtime, energy and carbon, the scheduler, vision inspection, "
            "security, or what the cell "
            "is doing right now."
        ), []
    res = [call(n, a, ctx) for n, a in route(q, ctx, lean=lean)]
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
