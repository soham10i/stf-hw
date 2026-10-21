// The icon rail and the panel it opens, on the left of the 3D view. Unpinned, the panel floats
// over the canvas as frosted glass; pinned, it takes its own column and the canvas makes room.
// The grip on its edge drags to resize and clicks to fold. Which panels exist, and what they
// show, comes from the panel registry; this component only lays them out.
import { useEffect, useRef, useState } from "react";
import { Icon } from "../shared/icons";
import { useScrollMemory } from "../shared/scrollMemory";
import type { Panel, PanelCtx } from "./registry";

export const SIDE_MIN = 300, SIDE_MAX = 640;

export function SidePanel({ panels, active, open, pinned, width, onPick, onToggle, onPin, onWidth, ctx }: {
  panels: Panel[]; active: Panel; open: boolean; pinned: boolean; width: number;
  onPick: (id: string) => void; onToggle: () => void; onPin: () => void; onWidth: (w: number) => void; ctx: PanelCtx;
}) {
  // the width follows the pointer while dragging and is stored once, on release
  const [drag, setDrag] = useState<number | null>(null);
  const start = useRef<{ x: number; w: number; moved: boolean } | null>(null);
  // each panel opens at the top on its first visit after a load, and where it was left after that
  const body = useRef<HTMLDivElement>(null);
  useScrollMemory(open ? `panel:${active.id}` : "", () => body.current);
  const w = drag ?? width;

  // a floating panel closes with Escape
  useEffect(() => {
    if (!open || pinned) return;
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") onToggle(); };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [open, pinned, onToggle]);

  const grip = (
    <div className={`side-grip ${open ? "" : "closed"}`} role="separator" aria-orientation="vertical"
      aria-label={open ? "Drag to resize, click to fold the panel" : "Unfold the panel"} title={open ? "Drag to resize · click to fold" : "Unfold the panel"}
      onPointerDown={(e) => { e.currentTarget.setPointerCapture(e.pointerId); start.current = { x: e.clientX, w: width, moved: false }; }}
      onPointerMove={(e) => {
        const s = start.current;
        if (!s || !open) return;
        const dx = e.clientX - s.x;
        if (Math.abs(dx) > 3) s.moved = true;
        if (s.moved) setDrag(Math.max(SIDE_MIN, Math.min(SIDE_MAX, s.w + dx)));
      }}
      onPointerUp={() => {
        const s = start.current;
        start.current = null;
        if (s?.moved && drag !== null) onWidth(drag); else onToggle();
        setDrag(null);
      }}>
      <i />
    </div>
  );

  return (
    <>
      <nav className="rail" role="tablist" aria-label="Panels">
        {panels.map((p, i) => (
          <button key={p.id} role="tab" aria-selected={open && p.id === active.id} data-tip={p.label} data-key={i < 9 ? i + 1 : undefined} aria-label={p.label}
            className={open && p.id === active.id ? "on" : ""} onClick={() => onPick(p.id)}>
            <Icon name={p.icon} size={19} />
          </button>
        ))}
        <span className="rail-sp" />
        <button onClick={onToggle} data-tip={open ? "Hide panel" : "Show panel"} data-key="[" aria-label="Toggle the panel">
          <Icon name="panel" size={19} />
        </button>
      </nav>
      {open ? (
        <aside className={`side ${pinned ? "pinned" : "float"} ${drag !== null ? "dragging" : ""}`} aria-label={active.label} style={{ width: w }}>
          <div className="side-head">
            <span className="side-ico"><Icon name={active.icon} size={16} /></span><b>{active.label}</b>
            <button className={`ui-btn icon ghost side-pin ${pinned ? "on" : ""}`} onClick={onPin} aria-pressed={pinned}
              title={pinned ? "Unpin: float the panel over the 3D view (P)" : "Pin the panel beside the 3D view (P)"} aria-label="Pin the panel">
              <Icon name="pin" size={15} />
            </button>
            <button className="ui-btn icon ghost side-close" onClick={onToggle} title="Close the panel" aria-label="Close the panel">
              <Icon name="chevron" size={16} />
            </button>
          </div>
          <div className="side-body" ref={body}>{active.render(ctx)}</div>
          {grip}
        </aside>
      ) : grip}
    </>
  );
}
