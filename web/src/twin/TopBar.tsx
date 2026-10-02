// The twin's top bar: brand, the view picker (from the view registry), what the
// view shows, the backend status, the dashboard link and the theme.
import type { Theme } from "../shared/theme";
import { Icon, ThemeToggle } from "../shared/icons";
import type { View } from "./registry";

export type Status = "open" | "connecting" | "closed" | "standalone";
const CHIP: Record<Status, [cls: string, label: string, tip: string]> = {
  open: ["ok", "Live", ""],
  connecting: ["warn", "Connecting", ""],
  closed: ["", "Offline", ""],
  standalone: ["ok", "Simulation", "Runs entirely in your browser: the machine, its PLC cycle and every analysis are generated from one model."],
};

export function TopBar({ views, view, onView, status, statusTip, theme, toggleTheme }: {
  views: View[]; view: View; onView: (id: string) => void;
  status: Status; statusTip: string; theme: Theme; toggleTheme: () => void;
}) {
  const groups = Array.from(new Set(views.map((v) => v.group)));
  return (
    <header className="topbar">
      <div className="brand">
        <span className="brand-mark">STF</span>
        <div><b>Digital Twin</b><span>Smart Tabletop Factory</span></div>
      </div>
      <div className="view-pick">
        <select className="ui-select" value={view.id} onChange={(e) => onView(e.target.value)} aria-label="View">
          {groups.map((g) => (
            <optgroup key={g} label={g}>
              {views.filter((v) => v.group === g).map((v) => <option key={v.id} value={v.id}>{v.label}</option>)}
            </optgroup>
          ))}
        </select>
        <span className="view-info" tabIndex={0} aria-label="About this view">
          <Icon name="info" size={16} />
          <span className="view-pop">{view.about}</span>
        </span>
      </div>
      <div className="top-actions">
        <span className={`ui-chip ${CHIP[status][0]}`} title={[CHIP[status][2], statusTip].filter(Boolean).join("\n")}>
          <span className="ui-dot" />{CHIP[status][1]}
        </span>
        <a className="ui-btn" href={`${import.meta.env.BASE_URL}dashboard.html`}><Icon name="gauge" size={16} />Dashboard</a>
        <ThemeToggle theme={theme} toggle={toggleTheme} />
      </div>
    </header>
  );
}
