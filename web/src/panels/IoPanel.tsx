import type { ChainsDoc, Io3Doc } from "../shared/model";
import { Fill, Note, Proofs } from "./kit";

// Upgrade 3's remote I/O, drag chains and cabinet, straight from io_nodes.py,
// chains.py and plc_model.py.

export function IoPanel({ io, ch }: { io: Io3Doc; ch: ChainsDoc }) {
  const types = ["DI", "DO", "AI", "CNT", ...(Object.values(io.nodes).some((n) => n.slices.some((s) => s.type === "IOL")) ? ["IOL"] : [])];
  return (
    <section className="panel upgrade io3">
      <p className="sf-line">{Object.keys(io.nodes).length} I/O nodes · {ch.rows.length} drag chains · 1 cabinet, all 5 export checks pass</p>

      <h3>I/O nodes <em className="sf-std">Modbus TCP · channels used</em></h3>
      <div className="io-grid" style={{ gridTemplateColumns: `minmax(56px, auto) repeat(${types.length}, minmax(0, 1fr))` }}>
        <span />{types.map((t) => <em key={t}>{t}</em>)}
        {Object.entries(io.nodes).map(([m, n]) => [
          <b key={m} title={`${n.where} · ${n.length} mm rail`}>{m}</b>,
          ...types.map((t) => {
            const sl = n.slices.filter((x) => x.type === t);
            const used = sl.reduce((a, x) => a + x.channels.filter(Boolean).length, 0);
            const cap = sl.reduce((a, x) => a + x.channels.length, 0);
            return cap ? <Fill key={m + t} v={used / cap} limit={1 - io.spare_min} title={`${m} ${t}: ${used}/${cap} channels`} /> : <span key={m + t} className="io-na">–</span>;
          }),
        ])}
      </div>
      <Note title="What changed">
        Each module's ST3 now lands on a node beside its PCB. Only an Ethernet line and a fused 24 V feed run
        to the cabinet (the 34-way bundles are gone). Every signal is on exactly one channel, with at least{" "}
        {Math.round(io.spare_min * 100)} % of each type spare. The VGR's own plate lies wholly under its arm's
        sweep, so its node stands in the free corner.
      </Note>

      <h3>Drag chains <em className="sf-std">fill · bend radius</em></h3>
      <ul className="sf-rows io-chains">
        {ch.rows.map((r) => (
          <li key={r.module + r.id} title={`${r.devices.length} devices: ${r.devices.join(", ")}\n${r.conductors} conductors · L ${r.length} mm · stroke ${r.stroke[1] - r.stroke[0]} mm`}>
            <b>{r.module}</b><span>{r.id}</span>
            <Fill v={r.fill} limit={ch.rules.fill_max} /><em>{Math.round(r.fill * 100)} %</em>
            <i className={r.R >= r.bend_min ? "plr-a" : "plr-e"}>{r.R >= r.bend_min ? "✓" : "✗"} R {r.R} ≥ {r.bend_min}</i>
          </li>
        ))}
      </ul>
      <Note title="Chain rules and the swivel">{ch.swivel}. Rules: {ch.rules.bend}, fill ≤ {Math.round(ch.rules.fill_max * 100)} %,
        unsupported span ≤ {ch.rules.self_support_mm} mm. {ch.sizes}. Open “Drag chain” under Mechanisms in the view list for the chain in 3D.</Note>

      <h3>Cabinet <em className="sf-std">EN 60204-1</em></h3>
      <div className="io-rail" title="3 DIO + AIO out; Ethernet switch + 4-ch electronic breaker in. PE on its own busbar, power and signal in separate ducts.">
        <span>DIN rail</span><Fill v={io.rail.used_mm / io.rail.length_mm} limit={0.8} />
        <em>{io.rail.used_mm} / {io.rail.length_mm} mm · {Math.round(io.rail.free * 100)} % free</em>
      </div>

      <Proofs items={[
        "allocation: every Belegungsplan signal on exactly one channel, ≥ 20 % spare per type",
        "placement: every node clear of every part, every swept hazard zone and the VGR sweep",
        "chains: length fits the stroke, bend radius, fill, self-supporting span, and every moving device on a chain path",
        "each chain's envelope, at every pose, is in the module proofs, check_cross and both VGR tours",
        "cabinet: rail ≥ 20 % free; the wiring router keeps every cable out of the belts' lanes and the cookie's path",
      ]} />
    </section>
  );
}
