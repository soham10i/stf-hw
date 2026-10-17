"""
The PLC reference (docs/plc/), written from the exports the twin itself runs on - so it is the
program the browser compiles and runs, not a description of it:

  web/public/hbw_parts_up12.json   control: units, steps, transitions, jobs, alarms, policies,
                                   jog permits, traceability; plc: the cabinet; io3: remote I/O
  web/public/sil/plc.json          the compiled program's I/O image (addresses, signals)
  web/public/sil/sil.json          the software-in-the-loop run: compiler, findings, checks, mutants
  web/public/sil/stf_plc.st        the IEC 61131-3 source itself (line numbers for each block)
  web/public/controller.json       the adaptor PCB and the 24 V I/O conventions

Every section ends with its sources: file paths, and line numbers into the source, so an answer
built from a passage can say exactly where it is from. The copilot's knowledge base indexes these
pages (`make copilot`), and the dashboard's Docs page shows them with their diagrams.

    python3 docs/gen/plc_docs.py          (or `make plc-docs`)
"""

from __future__ import annotations

import json
import os
import re

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
OUT = os.path.join(ROOT, "docs", "plc")
EXPORT = "web/public/hbw_parts_up12.json"
PLC = "web/public/sil/plc.json"
SIL = "web/public/sil/sil.json"
ST = "web/public/sil/stf_plc.st"
BOARD = "web/public/controller.json"
GEN = "docs/gen/plc_docs.py"
MODULE = {
    "hbw": "high-bay warehouse",
    "vgr": "vacuum gripper robot",
    "oven": "multi-processing oven",
    "sorting": "sorting line",
}
ARG = {"c": "cookie", "m": "mould", "slot": "slot", "bay": "bay", "src": "source"}
FB = {
    "crane": "FB_Crane",
    "belt": "FB_Belt",
    "arm": "FB_Arm",
    "door": "FB_Door",
    "sauger": "FB_Sauger",
    "turntable": "FB_Turntable",
    "ovenbelt": "FB_Ovenbelt",
    "line": "FB_Line",
}


def load(rel: str):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return json.load(f) if rel.endswith(".json") else f.read()


def st_lines(src: str) -> dict[str, tuple[int, int]]:
    """Each POU of the source: its first and last line."""
    starts = [
        (m.group(2), src[: m.start()].count("\n") + 1)
        for m in re.finditer(r"^(FUNCTION_BLOCK|PROGRAM|FUNCTION|CONFIGURATION)\s+(\w+)", src, re.M)
    ]
    total = src.count("\n") + 1
    return {
        name: (a, (starts[i + 1][1] - 1) if i + 1 < len(starts) else total)
        for i, (name, a) in enumerate(starts)
    }


def sources(*items: str) -> str:
    return "\n*Sources: " + "; ".join(f"`{s}`" for s in items) + ".*\n"


def esc(s) -> str:
    return str(s).replace("|", "\\|").replace("\n", " ")


def table(head: list[str], rows: list[list]) -> str:
    out = ["| " + " | ".join(head) + " |", "|" + "|".join("---" for _ in head) + "|"]
    out += ["| " + " | ".join(esc(c) for c in r) + " |" for r in rows]
    return "\n".join(out) + "\n"


def write(name: str, text: str) -> None:
    with open(os.path.join(OUT, name), "w", encoding="utf-8") as f:
        f.write(
            text.rstrip() + f"\n\n*Generated from the twin's exports by `{GEN}`; do not edit.*\n"
        )


# ----------------------------------------------------------------------------- the chapters
def overview(d, plc, sil, src_lines) -> str:
    c = d["control"]
    units = c["units"]
    by_mod: dict[str, list[str]] = {}
    for u, x in units.items():
        by_mod.setdefault(x["module"], []).append(u)
    io = plc["io"]
    lines = [
        "# PLC program: overview",
        "",
        "The Smart Tabletop Factory is run by **one IEC 61131-3 program**: eight unit sequencers and",
        "an orchestrator, generated from the same models that prove the machine's motion. The twin",
        "compiles it with MatIEC to WebAssembly and runs it in the browser against the simulated plant",
        f"every {plc['scan_ms']} ms (software in the loop). Nothing in the 3D view moves unless this",
        "program drives an output.",
        "",
        "![The PLC panel in the 3D twin: the program running, its units' states and its I/O image, live](../images/docs/twin-plc.jpg)",
        "",
        "```plc-architecture",
        "```",
        "",
        "## Program structure",
        "",
        "- **Units**: one `FUNCTION_BLOCK` per unit. Each is a step sequence `INIT -> homing -> READY ->",
        "  job steps -> READY`, with `FAULT` and `ESTOP` reachable from every state. A unit drives only",
        "  its own outputs.",
        "- **Orchestrator** (`PROGRAM MAIN`): a PLC scan that, after every job completion, offers the units",
        "  jobs in one fixed priority order, following the dispatch policy (here: "
        f"`{c['policy']}`). It tracks the factory state: slots, moulds, belt ends, oven, bins.",
        "- **Positioning**: each axis is driven toward its own target and stops half a scan's travel",
        "  before it (the brake lead), so a three-axis robot move ends with every axis in tolerance.",
        "- **Watchdogs**: every step that moves something has a time limit (1.5 x nominal + 0.5 s); past",
        "  it the unit drops its outputs and goes to `FAULT` with an alarm.",
        "",
        "## The units",
        "",
        table(
            ["Unit", "Module", "Function block", "Outputs", "Jobs", "What it does", "Source lines"],
            [
                [
                    u,
                    MODULE.get(x["module"], x["module"]),
                    f"`{FB[u]}`",
                    " ".join(x["outputs"]),
                    ", ".join(x["jobs"]),
                    x["label"],
                    "{}-{}".format(*src_lines[FB[u]]),
                ]
                for u, x in units.items()
            ],
        ),
        "## Size of the program",
        "",
        table(
            ["Measure", "Value"],
            [
                ["source", f"{sil['st_lines']} lines of Structured Text"],
                ["compiler", sil["compiler"]],
                ["scan time", f"{plc['scan_ms']} ms"],
                ["digital inputs / outputs", f"{len(io['ix'])} / {len(io['qx'])}"],
                ["analogue / RFID words", f"{len(io['iw'])}"],
                ["encoder positions", f"{len(io['id'])}"],
                ["monitoring words for the HMI", f"{len(io['mw'])}"],
                ["units / jobs", f"{len(units)} / {len(plc['jobs'])}"],
                ["alarms", f"{len(c['alarms'])}"],
                [
                    "a 12-cookie order, in the loop",
                    f"{sil['order_s']} s ({sil['scans']} scans, {sil['decisions']} orchestrator decisions)",
                ],
                ["the same order, as the model predicts", f"{sil['model_s']} s"],
            ],
        ),
        "## How to read the chapters",
        "",
        "1. [Hardware and wiring](01-hardware.md): the controller, the remote I/O, the 24 V conventions.",
        "2. [I/O map](02-io-map.md): every signal with its address in the program.",
        "3. [Unit sequencers](03-units.md): every unit's steps, outputs, completion signals and limits.",
        "4. [Orchestrator and dispatch](04-orchestrator.md): jobs, priorities, the policies and why one deadlocks.",
        "5. [Alarms](05-alarms.md): every alarm, its cause, the machine's reaction and the recovery.",
        "6. [Safety and manual mode](06-safety.md): ESTOP, FAULT, the safety relay, jog permits.",
        "7. [Verification](07-verification.md): what compiling and running the program found and proves.",
        "8. [Traceability](08-traceability.md): moulds, RFID read points, colour bands and the trace record.",
        "",
        f"{len(by_mod)} modules: "
        + "; ".join(f"{MODULE.get(m, m)} ({', '.join(us)})" for m, us in by_mod.items())
        + ".",
        sources(ST, EXPORT + " (control)", PLC, SIL),
    ]
    return "\n".join(lines)


def hardware(d, board) -> str:
    parts = d["plc"]["parts"]
    io3 = d["io3"]
    nodes = io3["nodes"]
    rows = [[p["n"], p.get("note", "")] for p in parts if p.get("note")]
    node_rows = []
    for m, n in nodes.items():
        sl = n.get("slices", [])
        used = sum(1 for s in sl for ch in s.get("channels", []) if ch)
        total = sum(len(s.get("channels", [])) for s in sl)
        node_rows.append(
            [
                MODULE.get(m, m),
                n.get("where", ""),
                " ".join(f"{s['id']} ({s['type']})" for s in sl),
                f"{used} of {total}",
            ]
        )
    p = board.get("plc", {})
    f = board.get("factory", {})
    return "\n".join(
        [
            "# PLC hardware and wiring",
            "",
            "The control cabinet holds one controller and the safety circuit; each module has its own",
            "remote I/O node on its plate, reached over Ethernet (Modbus TCP). The modules keep their",
            "fischertechnik 24 V sensors and actuators, wired to the node through the adaptor PCB.",
            "",
            "![The control cabinet in the 3D twin: the controller, the 24 V supply, the safety relay and"
            " contactors on the DIN rail](../images/docs/cabinet.jpg)",
            "",
            "```plc-hardware",
            "```",
            "",
            "## Cabinet",
            "",
            table(["Part", "What it is"], rows),
            sources(EXPORT + " (plc.parts)"),
            "## Remote I/O nodes",
            "",
            "One node per module, so a module's cable run is short and a module can be replaced alone.",
            f"Slice sizes: {io3.get('sizes', '')}. Every node keeps at least {int(100 * io3.get('spare_min', 0))} % spare channels.",
            "",
            table(["Module", "Mounted", "Slices", "Channels used"], node_rows),
            sources(EXPORT + " (io3)"),
            "## Electrical conventions (24 V)",
            "",
            f"- **Inputs**: {p.get('inputs', '')}.",
            f"- **Outputs**: {p.get('outputs', '')}.",
            "- **Reversible motors** are switched by relay pairs on the adaptor PCB (R1-R8): one output per",
            "  direction; the program never drives both directions of one motor (a proof, chapter 7).",
            f"- **The original machine**: supply {f.get('supply', '')}, {f.get('digital_in', '')} digital inputs,",
            f"  {f.get('counter_in', '')} counter inputs ({f.get('encoders', '')} encoders), {f.get('analog_in', '')} analogue input,",
            f"  {f.get('outputs', '')} outputs.",
            "",
            "## The adaptor PCB",
            "",
            table(
                ["Block", "Function"],
                [[k, v] for k, v in board.get("board", {}).get("blocks", {}).items()],
            ),
            "## Where the documents disagree",
            "",
            "The extended description and the datasheets do not always agree; the model follows the",
            "datasheet and flags the difference:",
            "",
            table(
                ["What", "One document", "The other", "What to do"],
                [[x["what"], x["a"], x["b"], x["impact"]] for x in board.get("discrepancies", [])],
            ),
            sources(BOARD, board.get("source", "")),
        ]
    )


def io_map(plc) -> str:
    io = plc["io"]
    out = [
        "# PLC I/O map",
        "",
        "Every signal the program reads or writes, with its address in the process image. Inputs",
        "are sinking (the sensor switches +24 V onto the input), outputs sourcing.",
        "",
    ]
    for key, title, cols in [
        ("ix", "Digital inputs (%IX)", ["Address", "Module", "Signal", "Meaning"]),
        ("qx", "Digital outputs (%QX)", ["Address", "Module", "Signal", "Meaning"]),
    ]:
        out += [
            f"## {title}",
            "",
            table(
                cols,
                [
                    [r["addr"], MODULE.get(r["module"], r["module"]), r["signal"], r["desc"]]
                    for r in io[key]
                ],
            ),
        ]
    out += [
        "## Analogue and RFID words (%IW)",
        "",
        table(
            ["Address", "Name", "Meaning"], [[r["addr"], r["name"], r["desc"]] for r in io["iw"]]
        ),
        "## Encoder positions (%ID)",
        "",
        table(
            ["Address", "Unit", "Axis", "Meaning"],
            [[r["addr"], r["unit"], r["axis"], r["desc"]] for r in io["id"]],
        ),
        "## Monitoring words for the HMI (%MW)",
        "",
        "Written by the program every scan for the operator screen and the twin's PLC panel.",
        "",
        table(
            ["Address", "Name", "Meaning"], [[r["addr"], r["name"], r["desc"]] for r in io["mw"]]
        ),
        sources(PLC + " (io)", ST),
    ]
    return "\n".join(out)


def units(d, src_lines) -> str:
    c = d["control"]
    out = [
        "# PLC unit sequencers",
        "",
        "Each unit is a step sequence. A step sets its outputs, waits for its completion signal",
        "(`done`), and is watched by a time limit when it moves anything. Every state can fall to",
        "`ESTOP` (the safety relay drops `Enable`) and every moving step to `FAULT` (its watchdog).",
        "Times are the model's nominal times, in seconds.",
        "",
    ]
    for u, x in c["units"].items():
        a, b = src_lines[FB[u]]
        out += [
            f"## {u}: {x['label']}",
            "",
            f"Module: {MODULE.get(x['module'], x['module'])}. Outputs: {' '.join(x['outputs'])}. Jobs: {', '.join(x['jobs'])}.",
            f"Function block `{FB[u]}`, lines {a}-{b} of the source.",
            "",
            f"```plc-sfc {u}",
            "```",
            "",
        ]
        rows = []
        for s in x["states"]:
            rows.append(
                [
                    s["id"],
                    s.get("say", ""),
                    " ".join(s.get("out", [])) or "-",
                    s.get("done") or "-",
                    s.get("t", "-"),
                    s.get("limit", "-") if s.get("supervised") else "-",
                ]
            )
        out += [
            table(
                ["Step", "What happens", "Outputs on", "Done when", "Nominal (s)", "Watchdog (s)"],
                rows,
            )
        ]
        rec = [e for e in x["edges"] if e[0] in ("FAULT", "ESTOP")]
        if rec:
            out += [
                "Recovery: " + "; ".join(f"`{e[0]}` -> `{e[1]}` when {e[2]}" for e in rec) + ".",
                "",
            ]
        out += [sources(EXPORT + f" (control.units.{u})", f"{ST}#L{a}-L{b}")]
    return "\n".join(out)


def orchestrator(d, plc, src_lines) -> str:
    c = d["control"]
    a, b = src_lines["MAIN"]
    pol_rows = []
    for k, p in c["policies"].items():
        pol_rows.append(
            [
                ("**" + k + "**") if k == c["policy"] else k,
                p.get("say", ""),
                "deadlocks" if p.get("deadlock") else f"{p.get('makespan')} s",
                p.get("states", ""),
            ]
        )
    study = c.get("study", [])
    out = [
        "# PLC orchestrator and dispatch",
        "",
        f"`PROGRAM MAIN` (lines {a}-{b}) is the orchestrator: every scan it reads the units' state,",
        "and when a unit finishes a job it offers jobs again in one fixed priority order. A job is",
        "bound to its arguments (a cookie, a mould, a slot, a bay) and may need several units at once.",
        "",
        "## Jobs and the units they need",
        "",
        table(
            ["Job", "Units", "Bound to"],
            [
                [
                    j,
                    ", ".join(plc["job_units"].get(j, [])),
                    ", ".join(ARG.get(x, x) for x in plc["layout"].get(j, [])),
                ]
                for j in plc["jobs"]
            ],
        ),
        "## Dispatch policies",
        "",
        "Each policy was explored exhaustively over every order in which jobs can complete (every",
        "possible timing). The PLC runs the one in bold.",
        "",
        table(["Policy", "Rule", "12-cookie order", "States explored"], pol_rows),
    ]
    dl = [(k, p) for k, p in c["policies"].items() if p.get("deadlock")]
    for k, p in dl:
        out += [
            f"### Why `{k}` deadlocks",
            "",
            p.get("why", ""),
            "",
            "The trace that ends in the deadlock: "
            + " -> ".join(f"`{t}`" for t in p.get("trace", [])[:14])
            + ".",
            "",
        ]
    if study:
        keys = [k for k in study[0] if k != "bake_s"]
        out += [
            "## Bake time and order time",
            "",
            "How long a 12-cookie order takes as the bake gets longer: the oven becomes the bottleneck",
            "and the policies converge.",
            "",
            table(["Bake (s)", *keys], [[r["bake_s"], *[r[k] for k in keys]] for r in study]),
        ]
    out += [
        sources(
            EXPORT + " (control.policies, control.study)",
            PLC + " (jobs, job_units, layout)",
            f"{ST}#L{a}-L{b}",
        )
    ]
    return "\n".join(out)


def alarms(d) -> str:
    c = d["control"]
    out = [
        "# PLC alarms",
        "",
        "Every alarm the program can raise. On an alarm the unit drops its outputs and goes to",
        "`FAULT`; it is given no new job, and the other units finish their current step and hold.",
        "",
    ]
    by_unit: dict[str, list] = {}
    for a in c["alarms"]:
        by_unit.setdefault(a["unit"], []).append(a)
    for u, al in by_unit.items():
        out += [
            f"## {u}",
            "",
            table(
                ["Code", "Alarm", "Cause", "Reaction", "Recovery"],
                [
                    [
                        a["code"],
                        a["text"],
                        a.get("cause", ""),
                        a.get("reaction", ""),
                        a.get("recovery", ""),
                    ]
                    for a in al
                ],
            ),
        ]
    out += [sources(EXPORT + " (control.alarms)")]
    return "\n".join(out)


def safety(d) -> str:
    c = d["control"]
    jog = c.get("jog", [])
    return "\n".join(
        [
            "# PLC safety and manual mode",
            "",
            "## Emergency stop and faults",
            "",
            "- **ESTOP**: the two-channel safety relay K0 drops `Enable` for every unit at once. Every state",
            "  has a transition to `ESTOP` on `NOT Enable`; outputs are off in `ESTOP`. Leaving it needs the",
            "  reset S3 through the safety relay, then the unit homes again (`ESTOP -> INIT`).",
            "- **FAULT**: a watchdog or a failed sensor puts one unit in `FAULT` with its alarm. Outputs are",
            "  off; the operator clears the cause and acknowledges on the HMI (`FAULT -> READY` on `Ack AND",
            "  Enable`).",
            "- **Force-guided contactors K1 and K2** switch the actuators' 24 V, so a stop removes the power",
            "  that moves anything, not only the program's command.",
            "- Outputs are off in `INIT`, `READY`, `FAULT` and `ESTOP` (proved, chapter 7).",
            "",
            "## Manual jog permits",
            "",
            "In manual mode an axis may be jogged only when the model says the move is safe from where",
            "the machine is:",
            "",
            table(
                ["Unit", "Axis", "Outputs", "Allowed when", "Checked by"],
                [[j["unit"], j["axis"], j["out"], j["when"], j["model"]] for j in jog],
            ),
            "## Design rules the layout keeps",
            "",
            *[f"- {x}" for x in d.get("interlocks", [])],
            "",
            "Retired outputs (driven by nothing, after the upgrades replaced their actuators): "
            + "; ".join(
                f"{MODULE.get(m, m)}: {' '.join(q)}" for m, q in c.get("retired", {}).items()
            )
            + ".",
            sources(
                EXPORT + " (control.units edges, control.jog, interlocks, control.retired)",
                EXPORT + " (plc.parts: safety_relay_K0, contactor_K1, contactor_K2)",
            ),
        ]
    )


def verification(sil) -> str:
    rows = [[f["id"], f["kind"], f["text"]] for f in sil["findings"]]
    mut = [
        [m["id"], m["what"], "caught" if m["caught"] else "MISSED", m["by"]] for m in sil["mutants"]
    ]
    chk = [[k, "pass" if v else "FAIL"] for k, v in sil["checks"].items()]
    return "\n".join(
        [
            "# PLC verification",
            "",
            "The program is checked three ways: proofs on the model it is generated from, a compiler, and",
            "a run of the compiled program against the simulated plant (software in the loop).",
            "",
            "## Proofs on the model",
            "",
            "1. Every unit state reaches `READY` and `ESTOP`; outputs are off in `INIT`, `READY`, `FAULT` and",
            "   `ESTOP`; no motor is driven both ways; every signal is in the Belegungsplan; every motion",
            "   has a timeout.",
            "2. The orchestrator, explored exhaustively over every completion order (every possible",
            "   timing), never deadlocks, conserves 12 cookies and 12 moulds, and ends with every cookie in",
            "   its bin.",
            "3. Every cookie's trace record is complete, and its flavour is confirmed by the colour sensor.",
            "",
            sources("stf-cad/hbw/control.py (module docstring: PROOFS)"),
            "## Compiling and running it",
            "",
            f"Compiler: {sil['compiler']}. The compiled program ran a 12-cookie order against the plant:",
            f"homed at {sil['homed_at']} s, done at {sil['done_at']} s, {sil['scans']} scans, {sil['decisions']}",
            f"orchestrator decisions; the model predicts {sil['model_s']} s.",
            "",
            table(["Check", "Result"], chk),
            "## What compiling and running found",
            "",
            "The first program (written as text by Upgrade 4) did not compile, and could not have run. Each",
            "finding was fixed in the generator, and the run repeated:",
            "",
            table(["Id", "Kind", "Finding"], rows),
            "## Mutants: can the checks fail?",
            "",
            "Deliberate faults put into the program; each must be caught by the run:",
            "",
            table(["Id", "Fault", "Result", "How it was caught"], mut),
            sources(SIL, "stf-cad/hbw/sil/iec.py (module docstring)"),
        ]
    )


def traceability(d) -> str:
    c = d["control"]
    tr = c.get("trace", [])
    ex = next((r for r in tr if r.get("kind") == "production"), {})
    return "\n".join(
        [
            "# PLC traceability",
            "",
            "Every cookie travels in a tagged mould (Werkstuecktraeger). The belt's two RFID read points",
            "read the tag; the sorting line's colour sensor confirms the flavour before the cookie is",
            "ejected into its bin; the program writes one trace record per cookie.",
            "",
            "## Moulds",
            "",
            table(["Slot", "Mould"], [[k, v] for k, v in c.get("moulds", {}).items()]),
            "## RFID read points",
            "",
            table(["Point", "Where"], [[k, v] for k, v in c.get("read_points", {}).items()]),
            f"Geometry: {json.dumps(c.get('rfid', {}))} (mm, mm/s).",
            "",
            "## Colour bands (sensor A4, mV)",
            "",
            table(
                ["Bin", "From (mV)", "To (mV)"],
                [[k, v[0], v[1]] for k, v in c.get("bands", {}).items()],
            ),
            "## A trace record",
            "",
            "```json",
            json.dumps(ex, indent=1)[:1500],
            "```",
            "",
            f"Assumed values: {c.get('assumed', '')}.",
            sources(
                EXPORT
                + " (control.moulds, control.read_points, control.rfid, control.bands, control.trace)"
            ),
        ]
    )


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    d, plc, sil, src, board = load(EXPORT), load(PLC), load(SIL), load(ST), load(BOARD)
    lines = st_lines(src)
    write("README.md", overview(d, plc, sil, lines))
    write("01-hardware.md", hardware(d, board))
    write("02-io-map.md", io_map(plc))
    write("03-units.md", units(d, lines))
    write("04-orchestrator.md", orchestrator(d, plc, lines))
    write("05-alarms.md", alarms(d))
    write("06-safety.md", safety(d))
    write("07-verification.md", verification(sil))
    write("08-traceability.md", traceability(d))
    print(f"wrote {OUT}: 9 chapters")


if __name__ == "__main__":
    main()
