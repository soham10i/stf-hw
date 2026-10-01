// The icon rail and the panel it opens. Which panels exist, and what they show,
// comes from the panel registry; this component only lays them out.
import { Icon } from "../shared/icons";
import type { Panel, PanelCtx } from "./registry";

export function SidePanel({ panels, active, open, onPick, onToggle, ctx }: {
  panels: Panel[]; active: Panel; open: boolean;
  onPick: (id: string) => void; onToggle: () => void; ctx: PanelCtx;
}) {
  return (
    <>
      {open && (
        <aside className="side" aria-label={active.label}>
          <div className="side-head">
            <Icon name={active.icon} size={17} /><b>{active.label}</b>
            <button className="ui-btn icon ghost" onClick={onToggle} title="Close the panel" aria-label="Close the panel">
              <Icon name="chevron" size={16} />
            </button>
          </div>
          <div className="side-body">{active.render(ctx)}</div>
        </aside>
      )}
      <nav className="rail" role="tablist" aria-label="Panels">
        {panels.map((p) => (
          <button key={p.id} role="tab" aria-selected={open && p.id === active.id} data-tip={p.label} aria-label={p.label}
            className={open && p.id === active.id ? "on" : ""} onClick={() => onPick(p.id)}>
            <Icon name={p.icon} size={19} />
          </button>
        ))}
        <span className="rail-sp" />
        <button onClick={onToggle} data-tip={open ? "Hide panel" : "Show panel"} aria-label="Toggle the panel">
          <Icon name="panel" size={19} />
        </button>
      </nav>
    </>
  );
}
