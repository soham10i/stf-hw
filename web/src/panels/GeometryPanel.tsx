import type { CadDoc } from "../shared/model";
import { Note, Title } from "./kit";

// Side panel: what the 3D geometry is made of and where it came from (hbw_export.py),
// and the cookies the pipeline conserves.
export function GeometryPanel({ doc }: { doc: CadDoc }) {
  const groups = doc.parts.reduce<Record<string, number>>((a, p) => {
    a[p.g] = (a[p.g] ?? 0) + 1;
    return a;
  }, {});
  const io = doc.parts.filter((p) => p.tag);
  return (
    <section className="panel">
      <Title lead="What the 3D machine is made of, generated from one parameter table and exported only after its proofs pass.">
        Generated geometry</Title>
      <Note title="Where it comes from">
        Emitted from <code>stf-cad/hbw/hbw_model.py</code>, the same table that builds
        <code> STF_HBW.FCStd</code>. Exported only after the clearance proof passes.
      </Note>
      <table className="kv">
        <tbody>
          {Object.entries(groups).map(([g, n]) => (
            <tr key={g}>
              <td>{g}</td>
              <td className="num">{n}</td>
            </tr>
          ))}
          <tr>
            <td>
              <b>total</b>
            </td>
            <td className="num">
              <b>{doc.parts.length}</b>
            </td>
          </tr>
        </tbody>
      </table>
      <PipelinePanel doc={doc} />
      <h3>I/O on this module</h3>
      <table className="kv">
        <tbody>
          {io.map((p) => (
            <tr key={p.n}>
              <td>{p.tag}</td>
              <td>{p.n}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

// The pipeline: the one place cookies exist, and the rules that keep them safe.
function PipelinePanel({ doc }: { doc: CadDoc }) {
  const pl = doc?.pipeline;
  if (!pl) return null;
  const counts: Record<string, number> = {};
  for (const [, v] of Object.entries(pl.initial as Record<string, [string, string[]]>)) {
    counts[v[0]] = (counts[v[0]] ?? 0) + 1;
  }
  return (
    <>
      <h3>
        Cookies <span className="muted">— {pl.n_cookies} in the system, conserved</span>
      </h3>
      <table className="kv">
        <tbody>
          {Object.entries(pl.flavours as Record<string, any>).map(([name, f]) => (
            <tr key={name}>
              <td>
                <span
                  style={{
                    display: "inline-block",
                    width: 10,
                    height: 10,
                    marginRight: 7,
                    background: f.colour,
                    borderRadius: 2,
                  }}
                />
                {name}
              </td>
              <td className="num">{counts[name] ?? 0}</td>
              <td className="muted">
                ~{f.mV} mV → {f.bin}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <Note title="Why these three flavours">
        The Farbsensor measures reflected brightness, not colour, so the three flavours are
        chosen to separate on exactly that. {pl.transfers.length} transfers per full cycle.
      </Note>
      <h3>Safety</h3>
      <ul className="safety">
        {(pl.safety as string[]).map((t, i) => (
          <li key={i}>{t}</li>
        ))}
      </ul>
    </>
  );
}
