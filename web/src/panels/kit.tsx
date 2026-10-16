// Building blocks shared by the side panels: a header with a link to the full
// dashboard page, and the folded notes, proofs and sub-tabs.
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

/** Sub-tabs inside one side panel; the choice is remembered per panel. */
export function SubTabs<T extends string>({ id, tabs, value, onChange }: {
  id: string; tabs: [T, string][]; value: T; onChange: (v: T) => void;
}) {
  return (
    <div className="ui-seg np-subtabs" role="tablist" aria-label={id}>
      {tabs.map(([k, label]) => (
        <button key={k} role="tab" aria-selected={k === value} className={k === value ? "on" : ""} onClick={() => onChange(k)}>{label}</button>
      ))}
    </div>
  );
}

/** What the checks verified, as one line; hover a part for its detail. */
export function Verified({ ok, items }: { ok: boolean; items: [string, string?][] }) {
  return (
    <p className={`plc-proof ${ok ? "ok" : "bad"}`}>
      <b>{ok ? "Verified" : "Check failed"}</b>{" "}
      {items.map(([t, tip], i) => <span key={t} title={tip}>{i ? " · " : ""}{t}</span>)}
    </p>
  );
}
