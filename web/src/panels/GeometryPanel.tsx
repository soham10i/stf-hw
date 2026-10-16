import type { CadDoc } from "../shared/model";
import { Fill, Note } from "./kit";

// Side panel: what the 3D geometry is made of and where it came from (hbw_export.py),
// and the cookies the pipeline conserves.
export function GeometryPanel({ doc }: { doc: CadDoc }) {
  const groups = Object.entries(doc.parts.reduce<Record<string, number>>((a, p) => {
    a[p.g] = (a[p.g] ?? 0) + 1;
    return a;
  }, {})).sort((a, b) => b[1] - a[1]);
  const most = groups[0]?.[1] ?? 1;
  const io = doc.parts.filter((p) => p.tag);
  return (
    <section className="panel">
      <p className="sf-line">{doc.parts.length} parts from one parameter table, exported only after the proofs pass</p>
      <h3>Parts</h3>
      <div className="geo-parts">
        {groups.map(([g, n]) => [<span key={g}>{g}</span>, <Fill key={g + "f"} v={n / most} />, <b key={g + "n"}>{n}</b>])}
      </div>
      <PipelinePanel doc={doc} />
      <details className="hmi-fold">
        <summary>I/O on this module <em>{io.length} tags</em></summary>
        <ul className="sf-rows">{io.map((p) => <li key={p.n}><b>{p.tag}</b><span>{p.n}</span></li>)}</ul>
      </details>
      <Note title="Where it comes from">
        Emitted from <code>stf-cad/hbw/hbw_model.py</code>, the same table that builds
        <code> STF_HBW.FCStd</code>. Exported only after the clearance proof passes.
      </Note>
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
  const safety = pl.safety as string[];
  return (
    <>
      <h3>Cookies <em className="sf-std">{pl.n_cookies} in the system, conserved</em></h3>
      <div className="geo-cookies">
        {Object.entries(pl.flavours as Record<string, { colour: string; mV: number; bin: string }>).map(([name, f]) => (
          <span key={name} title={`colour sensor ~${f.mV} mV`}><i style={{ background: f.colour }} />{name} <b>{counts[name] ?? 0}</b> → {f.bin}</span>
        ))}
      </div>
      <details className="hmi-fold">
        <summary>Pipeline safety rules <em>{safety.length}</em></summary>
        <ul className="sf-how">{safety.map((t, i) => <li key={i}>{t}</li>)}</ul>
      </details>
      <Note title="Why these three flavours">
        The Farbsensor measures reflected brightness, not colour, so the three flavours are
        chosen to separate on exactly that. {pl.transfers.length} transfers per full cycle.
      </Note>
    </>
  );
}
