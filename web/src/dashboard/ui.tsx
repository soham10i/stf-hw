// The dashboard's shared widgets: headline figures, cards (with their guide hint), the page guide
// and the simple horizontal bars.
import { createContext, useContext } from "react";


















import { GUIDE, TERMS, cardHelp } from "./guide";


export function Kpi({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: string }) {
  return <div className={`db-kpi ${tone ?? ""}`}><span>{label}</span><b>{value}</b>{sub && <em>{sub}</em>}</div>;
}
export const PageCtx = createContext("overview");
export function Card({ title, children, wide, extra }: { title: string; children: React.ReactNode; wide?: boolean; extra?: React.ReactNode }) {
  const help = cardHelp(useContext(PageCtx), title);
  return (
    <section className={`db-card ${wide ? "wide" : ""}`}>
      <h3>{title}{help && <i className="db-help" title={help} aria-label={help}>i</i>}{extra}</h3>
      {children}
    </section>
  );
}

/** The page's guide: what it is for, how to read it, its sections and the terms it uses. */
export function GuideBox({ page, onClose }: { page: string; onClose: () => void }) {
  const g = GUIDE[page];
  if (!g) return null;
  const terms = g.terms.filter((k) => TERMS[k]).map((k) => [k, TERMS[k]] as const);
  return (
    <aside className="db-guide" aria-label="Guide to this page">
      <div className="db-guide-h"><b>Guide · {g.title}</b><button className="ui-btn ghost" onClick={onClose}>Hide</button></div>
      <p className="db-guide-what">{g.what}</p>
      <div className="db-guide-cols">
        <div><h4>How to read it</h4><ol>{g.read.map((r) => <li key={r}>{r}</li>)}</ol></div>
        <div><h4>On this page</h4><dl>{g.sections.map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}</dl></div>
      </div>
      {terms.length > 0 && (
        <details className="db-guide-terms"><summary>Terms used here · {terms.length}</summary>
          <dl>{terms.map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}</dl></details>
      )}
      <p className="db-guide-src">Data: {g.source}</p>
    </aside>
  );
}
export function HBars({ rows, max, unit, hl }: { rows: [string, number, string?][]; max: number; unit: string; hl?: string }) {
  return (
    <div className="db-bars">
      {rows.map(([k, v, col]) => (
        <div key={k} className={k === hl ? "hl" : ""}><span>{k}</span>
          <i style={{ width: `${Math.max(0.5, (v / (max || 1)) * 100)}%`, background: col }} /><b>{Math.round(v * 10) / 10} {unit}</b></div>
      ))}
    </div>
  );
}
