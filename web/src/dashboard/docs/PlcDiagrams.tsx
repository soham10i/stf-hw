// The PLC reference's figures, drawn from the export the program is generated from: a unit's
// sequence as an SFC (IEC 61131-3 sequential function chart: steps, transitions, the outputs a
// step sets and the signal that ends it), the program's structure, and the hardware's network.

type State = { id: string; say?: string; out?: string[]; done?: string | null; t?: number; limit?: number; supervised?: boolean };
type Unit = { module: string; outputs: string[]; label: string; states: State[]; edges: [string, string, string][]; jobs: string[] };
export type Control = { units: Record<string, Unit>; policy: string };

const MOD: Record<string, string> = { hbw: "warehouse", vgr: "robot", oven: "oven", sorting: "sorting" };
const W = 188, H = 52, GAP = 22, COL = 214;

/** One unit's sequence: homing, then one column per job, each leaving READY and returning to it. */
export function Sfc({ c, unit }: { c: Control; unit: string }) {
  const u = c.units[unit];
  if (!u) return <p className="doc-muted">No unit "{unit}" in this export.</p>;
  const by = (p: (s: State) => boolean) => u.states.filter(p);
  const cols: { title: string; steps: State[] }[] = [
    { title: "homing", steps: [...by((s) => s.id === "INIT"), ...by((s) => s.id.startsWith("H:")), ...by((s) => s.id === "READY")] },
    ...u.jobs.map((j) => ({ title: `job: ${j}`, steps: by((s) => s.id.startsWith(`${j}.`)) })),
  ].filter((x) => x.steps.length);
  const rows = Math.max(...cols.map((x) => x.steps.length));
  const width = cols.length * COL + 20, height = 46 + rows * (H + GAP) + 40;
  const done = (s: State) => (s.done ? String(s.done).replace(/\|pos_(\w+) - (\d+)\| <= 1.*/, "$1 at $2") : "");
  return (
    <div className="sfc-wrap">
      <svg className="sfc" width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img"
        aria-label={`Sequence of the ${unit} unit: homing and ${u.jobs.length} jobs`}>
        {cols.map((col, ci) => {
          const x = 10 + ci * COL;
          return (
            <g key={col.title}>
              <text x={x + W / 2} y={18} className="sfc-col">{col.title}</text>
              {ci > 0 && <text x={x + W / 2} y={34} className="sfc-from">from READY, back to READY</text>}
              {col.steps.map((s, si) => {
                const y = 46 + si * (H + GAP);
                const init = s.id === "INIT" || s.id === "READY";
                return (
                  <g key={s.id}>
                    {si > 0 && (
                      <g className="sfc-trans">
                        <line x1={x + W / 2} y1={y - GAP} x2={x + W / 2} y2={y} />
                        <line x1={x + W / 2 - 10} y1={y - GAP / 2} x2={x + W / 2 + 10} y2={y - GAP / 2} />
                        <text x={x + W / 2 + 14} y={y - GAP / 2 + 4}>{done(col.steps[si - 1]) || "Enable"}</text>
                      </g>
                    )}
                    <rect x={x} y={y} width={W} height={H} rx={init ? 2 : 7} className={`sfc-step ${init ? "init" : ""} ${s.supervised ? "watched" : ""}`}>
                      <title>{`${s.id}: ${s.say ?? ""}${s.out?.length ? `\noutputs: ${s.out.join(" ")}` : ""}${s.done ? `\ndone: ${s.done}` : ""}${s.limit ? `\nwatchdog: ${s.limit} s` : ""}`}</title>
                    </rect>
                    {init && <rect x={x + 3} y={y + 3} width={W - 6} height={H - 6} rx={1} className="sfc-step-inner" />}
                    <text x={x + 10} y={y + 19} className="sfc-id">{s.id}</text>
                    {s.out?.length ? <text x={x + W - 10} y={y + 19} className="sfc-out" textAnchor="end">{s.out.join(" ")}</text> : null}
                    <text x={x + 10} y={y + 38} className="sfc-say">{(s.say ?? "").length > 30 ? `${s.say!.slice(0, 29)}…` : s.say}</text>
                  </g>
                );
              })}
            </g>
          );
        })}
        <text x={10} y={height - 12} className="sfc-note">Every step falls to ESTOP when Enable drops; a watched step (bold edge) to FAULT past its watchdog. Hover a step for its details.</text>
      </svg>
    </div>
  );
}

/** The program: MAIN orchestrating eight unit blocks, over the process image, each scan. */
export function Architecture({ c }: { c: Control }) {
  const units = Object.entries(c.units);
  const bw = 132, gap = 12, width = units.length * (bw + gap) + 20;
  return (
    <div className="sfc-wrap">
      <svg className="arch" width="100%" style={{ maxWidth: width }} viewBox={`0 0 ${width} 300`} role="img" aria-label="PLC program structure">
        <rect x={width / 2 - 170} y={12} width={340} height={58} rx={10} className="arch-main" />
        <text x={width / 2} y={36} className="arch-t">PROGRAM MAIN · orchestrator</text>
        <text x={width / 2} y={56} className="arch-s">policy “{c.policy}” · jobs in one fixed priority, every 5 ms scan</text>
        {units.map(([name, u], i) => {
          const x = 10 + i * (bw + gap);
          return (
            <g key={name}>
              <path d={`M ${width / 2} 70 C ${width / 2} 100, ${x + bw / 2} 92, ${x + bw / 2} 118`} className="arch-link" />
              <rect x={x} y={118} width={bw} height={72} rx={9} className={`arch-fb m-${u.module}`} />
              <text x={x + bw / 2} y={140} className="arch-t">FB_{name[0].toUpperCase() + name.slice(1)}</text>
              <text x={x + bw / 2} y={158} className="arch-s">{MOD[u.module] ?? u.module}</text>
              <text x={x + bw / 2} y={176} className="arch-s mono">{u.outputs.join(" ")}</text>
              <path d={`M ${x + bw / 2} 190 L ${x + bw / 2} 226`} className="arch-link" />
            </g>
          );
        })}
        <rect x={10} y={226} width={width - 20} height={52} rx={10} className="arch-io" />
        <text x={width / 2} y={248} className="arch-t">process image</text>
        <text x={width / 2} y={266} className="arch-s">%IX inputs · %QX outputs · %IW RFID + colour · %ID encoders · %MW HMI words</text>
      </svg>
    </div>
  );
}

/** The hardware: the controller, the switch, one remote I/O node per module, the safety circuit. */
export function Network() {
  const nodes = [["hbw", "warehouse"], ["vgr", "robot"], ["oven", "oven"], ["sorting", "sorting line"]];
  const width = 760;
  return (
    <div className="sfc-wrap">
      <svg className="arch" width="100%" style={{ maxWidth: width }} viewBox={`0 0 ${width} 310`} role="img" aria-label="PLC hardware network">
        <rect x={20} y={20} width={300} height={120} rx={12} className="arch-cab" />
        <text x={170} y={42} className="arch-t">control cabinet</text>
        <rect x={36} y={56} width={130} height={34} rx={7} className="arch-main" /><text x={101} y={78} className="arch-s">RevPi Core 3</text>
        <rect x={176} y={56} width={128} height={34} rx={7} className="arch-fb" /><text x={240} y={78} className="arch-s">Ethernet switch</text>
        <rect x={36} y={98} width={130} height={30} rx={7} className="arch-safe" /><text x={101} y={118} className="arch-s">K0 safety relay</text>
        <rect x={176} y={98} width={128} height={30} rx={7} className="arch-safe" /><text x={240} y={118} className="arch-s">K1 / K2 contactors</text>
        <text x={430} y={42} className="arch-s">Modbus TCP</text>
        <rect x={360} y={20} width={380} height={120} rx={12} className="arch-cab soft" />
        <text x={550} y={60} className="arch-s">24 V supply WDR-120 · 4-channel e-fuse, one feed per module</text>
        <text x={550} y={80} className="arch-s">safety circuit drops Enable and the actuator 24 V</text>
        {nodes.map(([m, label], i) => {
          const x = 20 + i * 185;
          return (
            <g key={m}>
              <path d={`M 240 90 C 240 170, ${x + 82} 160, ${x + 82} 200`} className="arch-link" />
              <rect x={x} y={200} width={165} height={84} rx={10} className={`arch-fb m-${m}`} />
              <text x={x + 82} y={224} className="arch-t">I/O node · {label}</text>
              <text x={x + 82} y={244} className="arch-s">DI · DO · counters{m === "hbw" ? " · IO-Link (RFID)" : ""}</text>
              <text x={x + 82} y={264} className="arch-s">ft 24 V sensors and motors</text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
