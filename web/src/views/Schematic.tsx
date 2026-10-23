// The wiring diagram of one module, drawn from the netlist (circuit/factoryCircuit.ts):
//   left    the PLC side - the RevPi DIO (original) or the remote I/O node's slices (upgraded)
//   middle  the adaptor PCB: one row per net it carries (its terminal, ribbon pin, relay)
//   right   the field parts, each with the pins it has wired
// A signal is a wire from pin to pin, each in its own lane so none overlap; a supply rail (a net
// many pins share) is a coloured stub with its name. Every wire is coloured by its voltage now.
import { useMemo } from "react";

import type { FactoryCircuit } from "../circuit/factoryCircuit";

const ROW = 18;
const HEAD = 24;
const COL_W = 210;
const GAP = 150;
const RAIL_MIN = 6; // a net with this many pins is drawn as a rail

interface Box { inst: string; title: string; sub: string; x: number; y: number; rows: { key: string; label: string; net: string }[] }

const colour = (v: number | null | undefined) =>
  v == null ? "var(--muted)" : v >= 20 ? "#d23a32" : v > 0 ? "#d99a1e" : "#3b7dd8";
const railName = (net: string, v: number | null | undefined) =>
  v == null ? net : v >= 20 ? `+${v} V · ${net}` : v > 0 ? `${v} V · ${net}` : `0 V · ${net}`;

export function Schematic({ circuit, module, tick, onPick }: { circuit: FactoryCircuit; module: string; tick: number; onPick: (inst: string) => void }) {
  const doc = circuit.doc;
  const parts = circuit.file.parts;

  const layout = useMemo(() => {
    const insts = doc.project.placed_parts.filter((p) => doc.modules[p.instance_id] === module);
    const netsOf = new Map<string, { net: string; pins: string[] }[]>();
    for (const n of doc.project.wire_nets) {
      for (const c of n.connections) {
        if (doc.modules[c.part_instance] !== module) continue;
        const list = netsOf.get(c.part_instance) ?? [];
        let row = list.find((r) => r.net === n.net_id);
        if (!row) { row = { net: n.net_id, pins: [] }; list.push(row); }
        row.pins.push(c.pin_label);
        netsOf.set(c.part_instance, list);
      }
    }
    const size = new Map(doc.project.wire_nets.map((n) => [n.net_id, n.connections.length]));
    const isPlc = (pid: string) => pid === "revpi_dio" || pid.startsWith("io_");
    const columns: string[][] = [
      insts.filter((p) => isPlc(p.part_id)).map((p) => p.instance_id),
      insts.filter((p) => p.part_id === "adaptor_pcb").map((p) => p.instance_id),
      insts.filter((p) => !isPlc(p.part_id) && p.part_id !== "adaptor_pcb").map((p) => p.instance_id),
    ];
    const boxes: Box[] = [];
    columns.forEach((col, ci) => {
      let y = 10;
      for (const inst of col) {
        const pid = doc.project.placed_parts.find((p) => p.instance_id === inst)!.part_id;
        const rows = (netsOf.get(inst) ?? [])
          .map((r) => ({ key: `${inst}|${r.net}`, label: r.pins.join(" · "), net: r.net }))
          .sort((a, b) => (size.get(a.net)! >= RAIL_MIN ? 1 : 0) - (size.get(b.net)! >= RAIL_MIN ? 1 : 0) || a.label.localeCompare(b.label, undefined, { numeric: true }));
        if (!rows.length) continue;
        boxes.push({ inst, title: inst.split(".").slice(1).join(".") || inst, sub: parts[pid].name, x: 10 + ci * (COL_W + GAP), y, rows });
        y += HEAD + rows.length * ROW + 14;
      }
    });
    // the pin positions, and each signal net's lane in the gap it crosses
    const at = new Map<string, { x: number; y: number; left: number; right: number; col: number }>();
    for (const b of boxes) {
      const col = Math.round((b.x - 10) / (COL_W + GAP));
      b.rows.forEach((r, i) => at.set(r.key, { x: b.x, y: b.y + HEAD + i * ROW + ROW / 2, left: b.x, right: b.x + COL_W, col }));
    }
    const signals = [...new Set(boxes.flatMap((b) => b.rows.map((r) => r.net)))].filter((n) => size.get(n)! < RAIL_MIN);
    const lane = new Map(signals.map((n, i) => [n, i]));
    const height = Math.max(...boxes.map((b) => b.y + HEAD + b.rows.length * ROW), 100) + 20;
    return { boxes, at, signals, lane, size, height, width: 10 + 3 * COL_W + 2 * GAP + 10 };
  }, [doc, module, parts]);

  // the voltage on every net now
  const volts = useMemo(() => {
    const m = new Map<string, number | null>();
    for (const d of circuit.evaluate()) if (d.netId) m.set(d.netId, d.volts);
    return m;
  }, [circuit, tick]); // eslint-disable-line react-hooks/exhaustive-deps

  const { boxes, at, signals, lane, size, height, width } = layout;
  // a wire between two pins of one net, through the net's lane in each gap it crosses
  const wires: JSX.Element[] = [];
  for (const net of signals) {
    const ends = boxes.flatMap((b) => b.rows.filter((r) => r.net === net).map((r) => at.get(r.key)!)).sort((a, b) => a.col - b.col || a.y - b.y);
    const c = colour(volts.get(net));
    for (let i = 1; i < ends.length; i++) {
      const a = ends[i - 1], b = ends[i];
      if (a.col === b.col) continue; // two pins of one column on one net: shown by the row label
      const lx = a.right + 10 + ((lane.get(net)! * 7) % (GAP - 20));
      wires.push(<path key={`${net}-${i}`} d={`M${a.right} ${a.y} H${lx} V${b.y} H${b.left}`} stroke={c} />);
    }
  }

  return (
    <div className="sch-wrap">
      <svg className="sch" viewBox={`0 0 ${width} ${height}`} width={width} height={height} role="img" aria-label={`Wiring diagram: ${module}`}>
        <g className="sch-wires">{wires}</g>
        {boxes.map((b) => (
          <g key={b.inst} className="sch-box" onClick={() => onPick(b.inst)}>
            <rect x={b.x} y={b.y} width={COL_W} height={HEAD + b.rows.length * ROW} rx={6} />
            <text x={b.x + 8} y={b.y + 15} className="sch-title">{b.title}</text>
            <text x={b.x + COL_W - 8} y={b.y + 15} className="sch-sub" textAnchor="end">{b.sub.slice(0, 22)}</text>
            {b.rows.map((r, i) => {
              const y = b.y + HEAD + i * ROW + ROW / 2;
              const rail = size.get(r.net)! >= RAIL_MIN;
              const v = volts.get(r.net);
              return (
                <g key={r.key}>
                  <circle cx={b.x} cy={y} r={2.5} fill={colour(v)} />
                  <circle cx={b.x + COL_W} cy={y} r={2.5} fill={colour(v)} />
                  <text x={b.x + 8} y={y + 4} className="sch-pin">{r.label.length > 26 ? `${r.label.slice(0, 25)}…` : r.label}</text>
                  {rail && <text x={b.x + COL_W - 8} y={y + 4} className="sch-rail" textAnchor="end" fill={colour(v)}>{railName(r.net, v).slice(0, 18)}</text>}
                  {!rail && v != null && <text x={b.x + COL_W - 8} y={y + 4} className="sch-v" textAnchor="end" fill={colour(v)}>{v} V</text>}
                </g>
              );
            })}
          </g>
        ))}
      </svg>
      <p className="el-legend">
        <i style={{ background: "#d23a32" }} /> +24 V <i style={{ background: "#d99a1e" }} /> 9 V <i style={{ background: "#3b7dd8" }} /> 0 V
        <i style={{ background: "var(--muted)" }} /> floating · rails (nets of {RAIL_MIN}+ pins) are labelled, not drawn · click a part for its sheet
      </p>
    </div>
  );
}
