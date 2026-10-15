// Building blocks shared by the side panels: a header with a link to the full
// dashboard page, a stat tile and a sparkline.
import { Icon } from "../shared/icons";

const BASE = import.meta.env.BASE_URL;
export const dashboardPage = (p: string) => `${BASE}dashboard.html?p=${p}`;

export function Head({ title, sub, page }: { title: string; sub: string; page: string }) {
  return (
    <div className="np-head">
      <div><b>{title}</b><span>{sub}</span></div>
      <a className="ui-btn" href={dashboardPage(page)} target="_blank" rel="noopener noreferrer">Full page <Icon name="external" size={13} /></a>
    </div>
  );
}

export function Stat({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: string }) {
  return <div className={`np-stat ${tone ?? ""}`}><span>{label}</span><b>{value}</b>{sub && <em>{sub}</em>}</div>;
}

export function Spark({ ys, color, h = 46, min, max }: { ys: number[]; color: string; h?: number; min?: number; max?: number }) {
  const W = 300, lo = min ?? Math.min(...ys), hi = max ?? Math.max(...ys);
  const d = ys.map((y, i) => `${i ? "L" : "M"}${((i / (ys.length - 1)) * W).toFixed(1)},${(h - 3 - ((y - lo) / (hi - lo || 1)) * (h - 6)).toFixed(1)}`).join("");
  return <svg viewBox={`0 0 ${W} ${h}`} className="np-spark" preserveAspectRatio="none"><path d={d} style={{ stroke: color }} /></svg>;
}

export function Empty({ text }: { text: string }) {
  return <p className="np-err">{text}</p>;
}

/** A panel's title, the upgrade it belongs to, and one line saying what it shows. */
export function Title({ children, up, lead }: { children: React.ReactNode; up?: string; lead?: React.ReactNode }) {
  return (
    <>
      <h2 className="np-title">{children}{up && <span className="np-up">{up}</span>}</h2>
      {lead && <p className="np-lead">{lead}</p>}
    </>
  );
}

/** Explanation that most readers can skip: closed until asked for. */
export function Note({ title = "About this", children }: { title?: string; children: React.ReactNode }) {
  return (
    <details className="np-note">
      <summary>{title}</summary>
      <div>{children}</div>
    </details>
  );
}

/** The checks that must pass before the model is exported - closed, with their count. */
export function Proofs({ items }: { items: React.ReactNode[] }) {
  return (
    <details className="np-note np-proofs">
      <summary>Proofs that gate this export <em>{items.length}</em></summary>
      <ul>{items.map((x, i) => <li key={i}>{x}</li>)}</ul>
    </details>
  );
}
