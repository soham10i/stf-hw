// The twin's top bar: brand, the view switcher (searchable, Cmd/Ctrl+K), the backend status,
// the order shortcut, the dashboard link and the theme.
import { useEffect, useMemo, useRef, useState } from "react";
import type { ThemeId } from "../shared/theme";
import { Icon, ThemeMenu } from "../shared/icons";
import type { View } from "./registry";

export type Status = "open" | "connecting" | "closed" | "standalone";
const CHIP: Record<Status, [cls: string, label: string, tip: string]> = {
  open: ["ok", "Live", ""],
  connecting: ["warn", "Connecting", ""],
  closed: ["", "Offline", ""],
  standalone: ["ok", "Simulation", "Runs entirely in your browser: the machine, its PLC cycle and every analysis are generated from one model."],
};
const MAC = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform);

/** The current view as a button; it opens a searchable list of every view. */
function ViewMenu({ views, view, onView }: { views: View[]; view: View; onView: (id: string) => void }) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [hi, setHi] = useState(0);
  const box = useRef<HTMLDivElement>(null);
  const hits = useMemo(() => {
    const t = q.trim().toLowerCase();
    return t ? views.filter((v) => `${v.label} ${v.group} ${v.about}`.toLowerCase().includes(t)) : views;
  }, [q, views]);

  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setOpen((o) => !o); }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, []);
  useEffect(() => {
    if (!open) return;
    setQ(""); setHi(Math.max(0, views.findIndex((v) => v.id === view.id)));
    const away = (e: PointerEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false); };
    window.addEventListener("pointerdown", away);
    return () => window.removeEventListener("pointerdown", away);
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  const choose = (v: View) => { onView(v.id); setOpen(false); };
  const groups = Array.from(new Set(hits.map((v) => v.group)));
  return (
    <div className="vm" ref={box}>
      <button className="vm-btn" onClick={() => setOpen(!open)} aria-haspopup="listbox" aria-expanded={open} title={view.about}>
        <span className="vm-group">{view.group}</span><b>{view.label}</b>
        <kbd>{MAC ? "⌘" : "Ctrl"} K</kbd><Icon name="down" size={14} />
      </button>
      {open && (
        <div className="vm-pop" role="dialog" aria-label="Switch view">
          <label className="vm-search"><Icon name="search" size={15} />
            <input autoFocus value={q} placeholder="Search views…" aria-label="Search views"
              onChange={(e) => { setQ(e.target.value); setHi(0); }}
              onKeyDown={(e) => {
                if (e.key === "ArrowDown") { e.preventDefault(); setHi((h) => Math.min(hits.length - 1, h + 1)); }
                else if (e.key === "ArrowUp") { e.preventDefault(); setHi((h) => Math.max(0, h - 1)); }
                else if (e.key === "Enter" && hits[hi]) choose(hits[hi]);
                else if (e.key === "Escape") setOpen(false);
              }} />
          </label>
          <div className="vm-list" role="listbox">
            {groups.map((g) => (
              <div key={g}>
                <em>{g}</em>
                {hits.filter((v) => v.group === g).map((v) => {
                  const i = hits.indexOf(v);
                  return (
                    <button key={v.id} role="option" aria-selected={v.id === view.id} className={`${i === hi ? "hi" : ""} ${v.id === view.id ? "cur" : ""}`}
                      onMouseEnter={() => setHi(i)} onClick={() => choose(v)}>
                      <b>{v.label}</b><span>{v.about}</span>
                    </button>
                  );
                })}
              </div>
            ))}
            {!hits.length && <p className="vm-none">No view matches “{q}”.</p>}
          </div>
        </div>
      )}
    </div>
  );
}

export function TopBar({ views, view, onView, status, statusTip, theme, setTheme, onOrder }: {
  views: View[]; view: View; onView: (id: string) => void;
  status: Status; statusTip: string; theme: ThemeId; setTheme: (t: ThemeId) => void; onOrder?: () => void;
}) {
  return (
    <header className="topbar">
      <div className="brand">
        <span className="brand-mark">STF</span>
        <div><b>Smart Tabletop Factory</b><span>Digital twin</span></div>
      </div>
      <ViewMenu views={views} view={view} onView={onView} />
      <div className="top-actions">
        <span className={`ui-chip top-status ${CHIP[status][0]}`} title={[CHIP[status][2], statusTip].filter(Boolean).join("\n")}>
          <span className="ui-dot" />{CHIP[status][1]}
        </span>
        {onOrder && <button className="ui-btn primary" onClick={onOrder} title="Open the order form" aria-label="New order"><Icon name="plus" size={15} /><span className="hide-sm">New order</span></button>}
        <a className="ui-btn ghost" href={`${import.meta.env.BASE_URL}dashboard.html`} aria-label="Dashboard"><Icon name="gauge" size={16} /><span className="hide-sm">Dashboard</span></a>
        <ThemeMenu theme={theme} setTheme={setTheme} />
      </div>
    </header>
  );
}
