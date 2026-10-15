import type { ChainsDoc, Io3Doc } from "../shared/model";
import { Note, Proofs, Title } from "./kit";

// Upgrade 3's remote I/O, drag chains and cabinet, straight from io_nodes.py,
// chains.py and plc_model.py.
export function IoPanel({ io, ch }: { io: Io3Doc; ch: ChainsDoc }) {
  const types = ["DI", "DO", "AI", "CNT", ...(Object.values(io.nodes).some((n) => n.slices.some((s) => s.type === "IOL")) ? ["IOL"] : [])];
  return (
    <section className="panel upgrade io3">
      <Title up="Upgrade 3" lead="Each module has its own I/O node; moving cables ride in drag chains; one tidy cabinet.">
        Remote I/O, chains, cabinet</Title>

      <h3>I/O nodes (Modbus TCP) · channels used</h3>
      <table className="kv up-table">
        <thead><tr><td>module</td>{types.map((t) => <td key={t} className="num">{t}</td>)}</tr></thead>
        <tbody>
          {Object.entries(io.nodes).map(([m, n]) => (
            <tr key={m} title={n.where}>
              <td>{m}<div className="muted small">{n.where} · {n.length} mm rail</div></td>
              {types.map((t) => {
                const sl = n.slices.filter((s) => s.type === t);
                const used = sl.reduce((a, s) => a + s.channels.filter(Boolean).length, 0);
                const cap = sl.reduce((a, s) => a + s.channels.length, 0);
                return <td key={t} className="num">{cap ? `${used}/${cap}` : "–"}</td>;
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <Note title="What changed">
        Each module's ST3 now lands on a node beside its PCB. Only an Ethernet line and a fused 24 V feed run
        to the cabinet (the 34-way bundles are gone). Every signal is on exactly one channel, with at least{" "}
        {Math.round(io.spare_min * 100)} % of each type spare. The VGR's own plate lies wholly under its arm's
        sweep, so its node stands in the free corner.
      </Note>

      <h3>Drag chains</h3>
      <table className="kv up-table">
        <thead><tr><td>chain</td><td className="num">stroke</td><td className="num">R</td><td className="num">fill</td></tr></thead>
        <tbody>
          {ch.rows.map((r) => (
            <tr key={r.module + r.id} title={r.devices.join(", ")}>
              <td>{r.module} {r.id}<div className="muted small">{r.devices.length} devices · {r.conductors} conductors · L {r.length} mm</div></td>
              <td className="num">{r.stroke[1] - r.stroke[0]}</td>
              <td className="num">{r.R} ≥ {r.bend_min}</td>
              <td className="num">{Math.round(r.fill * 100)} %</td>
            </tr>
          ))}
        </tbody>
      </table>
      <Note title="Chain rules and the swivel">{ch.swivel}. Rules: {ch.rules.bend}, fill ≤ {Math.round(ch.rules.fill_max * 100)} %,
        unsupported span ≤ {ch.rules.self_support_mm} mm. {ch.sizes}. Open “Drag chain” under Mechanisms in the view list for the chain in 3D.</Note>

      <h3>Cabinet (EN 60204-1)</h3>
      <table className="kv up-table">
        <tbody>
          <tr><td>DIN rail</td><td className="num">{io.rail.used_mm} / {io.rail.length_mm} mm</td>
            <td className={`num ${io.rail.free >= 0.2 ? "up-good" : "up-cost"}`}>{Math.round(io.rail.free * 100)} % free</td></tr>
          <tr><td colSpan={3} className="muted small">
            3 DIO + AIO out → Ethernet switch + 4-ch electronic breaker in. PE on its own busbar, power and
            signal in separate ducts.
          </td></tr>
        </tbody>
      </table>

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
