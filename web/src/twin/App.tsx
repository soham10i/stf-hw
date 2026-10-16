// The twin's shell. It owns only the view and the panel state; what the views and
// panels are lives in registry.tsx, the backend link in useBackend, the 3D machine
// in scene/HbwCad. One machine is shown: Upgrade 12, which contains U1-U11.
import { Canvas } from "@react-three/fiber";
import { useEffect, useMemo, useState } from "react";

import { HbwCadStage } from "../scene/Stage";
import { RATE } from "../scene/timeline";
import { useCadDoc } from "../shared/model";
import { ErrorBoundary } from "../shared/ErrorBoundary";
import { Icon } from "../shared/icons";
import { usePersistent } from "../shared/persist";
import { useTheme } from "../shared/theme";
import { ComponentView } from "../views/ComponentView";
import { useComponents } from "../views/componentModel";
import { ControllerView } from "../views/ControllerView";
import { useController } from "../views/controllerModel";
import { CONTROLLER_VIEW, MACHINE_VIEW, PANELS, componentViews, type PanelCtx } from "./registry";
import { SidePanel } from "./SidePanel";
import { TopBar } from "./TopBar";
import { useBackend } from "./useBackend";

export default function App() {
  const [theme, toggleTheme] = useTheme();
  const { scene, error: apiError, conn } = useBackend();
  const machine = useCadDoc();
  const comps = useComponents();
  const ctl = useController();
  const [phase, setPhase] = useState("");
  // react-three-fiber measures its parent with a ResizeObserver, which some embedded
  // browsers never fire initially: the Canvas then stays empty. Nudge it once the machine
  // is loaded (a timeout, not rAF: rAF does not run in a hidden tab).
  useEffect(() => {
    if (machine.doc) { const id = window.setTimeout(() => window.dispatchEvent(new Event("resize")), 50); return () => window.clearTimeout(id); }
  }, [machine.doc]);

  // ------------------------------------------------------------ the view
  const views = useMemo(() => [MACHINE_VIEW, CONTROLLER_VIEW, ...componentViews(comps.doc?.components)], [comps.doc]);
  const [viewId, setViewId] = useState(() => new URLSearchParams(location.search).get("view") ?? MACHINE_VIEW.id);
  const view = views.find((v) => v.id === viewId) ?? MACHINE_VIEW;
  useEffect(() => {
    const q = new URLSearchParams(location.search);
    q.delete("tab");                                   // the old per-upgrade views are gone
    if (view.id === MACHINE_VIEW.id) q.delete("view"); else q.set("view", view.id);
    history.replaceState(null, "", `${location.pathname}${q.toString() ? "?" + q : ""}`);
  }, [view.id]);

  // ----------------------------------------------------------- the panels
  const [showZones, setShowZones] = usePersistent("stf.zones", true);
  const [showCover, setShowCover] = usePersistent("stf.cover", true);
  const [open, setOpen] = usePersistent("stf.side.open", window.innerWidth >= 900);
  const [panelId, setPanelId] = usePersistent("stf.side.tab", "orders");
  const [pinned, setPinned] = usePersistent("stf.side.pinned", false);
  const [sideW, setSideW] = usePersistent("stf.side.width", 380);
  const nudge = () => requestAnimationFrame(() => window.dispatchEvent(new Event("resize")));
  const [netZonesAsked, setNetZones] = useState(false);
  const ctx: PanelCtx | null = machine.doc ? { doc: machine.doc, scene, showZones, setShowZones, setNetZones } : null;
  const panels = ctx ? PANELS.filter((p) => p.available(ctx)) : [];
  const active = panels.find((p) => p.id === panelId) ?? panels[0];
  const toggle = () => {
    setOpen(!open);
    nudge(); // the Canvas remeasures on resize; some embedded browsers need the nudge
  };
  const pick = (id: string) => {
    if (open && id === active?.id) return toggle();
    if (!open) toggle();
    setPanelId(id);
  };
  const netZones = open && active?.id === "safety" && netZonesAsked;
  const order = () => { if (!open) toggle(); setPanelId("orders"); };

  // keyboard: 1-9 open a panel, [ shows or hides it, P pins it (not while typing)
  useEffect(() => {
    if (view.kind !== "machine") return;
    const key = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (e.metaKey || e.ctrlKey || e.altKey || t.closest("input, textarea, select, [contenteditable]")) return;
      if (e.key === "[") toggle();
      else if (e.key.toLowerCase() === "p" && open) { setPinned(!pinned); nudge(); }
      else if (e.key.toLowerCase() === "c") setShowCover(!showCover);
      else if (/^[1-9]$/.test(e.key) && panels[+e.key - 1]) pick(panels[+e.key - 1].id);
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  });

  // the floating chrome keeps clear of the dock (62 px) and of an open panel
  const machineView = view.kind === "machine";
  const panelOpen = !!(ctx && active && open);
  const inset = 72 + (panelOpen ? sideW + 10 : 0);
  const vars = {
    "--vp-left": panelOpen && pinned ? `${inset}px` : "0px",
    "--tools-left": `${panelOpen && pinned ? 10 : inset}px`,
  } as React.CSSProperties;
  const waiting = phase === "Waiting for an order";

  return (
    <div className={`app ${machineView ? "immersive" : ""}`}>
      <TopBar views={views} view={view} onView={setViewId} theme={theme} toggleTheme={toggleTheme}
        status={conn.conn} onOrder={machineView && ctx ? order : undefined}
        statusTip={[scene && `layout ${scene.fingerprint}`, machine.doc && `cad ${machine.doc.fingerprint}`].filter(Boolean).join("  ·  ")} />

      {view.kind === "controller" && (ctl.doc ? <ControllerView doc={ctl.doc} /> : <div className="error">{ctl.err}</div>)}
      {view.kind === "component" && comps.doc && <ComponentView id={view.id} doc={comps.doc} />}

      {machineView && (
        <div className="body" style={vars}>
          {ctx && active && (
            <SidePanel panels={panels} active={active} open={open} pinned={pinned} width={sideW} ctx={ctx}
              onPick={pick} onToggle={toggle} onPin={() => { setPinned(!pinned); nudge(); }} onWidth={(w) => { setSideW(w); nudge(); }} />
          )}
          <div className="viewport">
            {(apiError || machine.err) && <div className="vp-errors">
              {apiError && <div className="error">{apiError}</div>}
              {machine.err && <div className="error">{machine.err}</div>}
            </div>}
            {machine.doc && (
              <ErrorBoundary>
                <Canvas shadows dpr={[1, 2]} gl={{ preserveDrawingBuffer: true }}>
                  <HbwCadStage doc={machine.doc} onPhase={setPhase} showZones={showZones && !netZones} netZones={netZones} showCover={showCover} />
                </Canvas>
              </ErrorBoundary>
            )}
          </div>
          <div className="vp-dock">
            <div className="vp-bar">
              <span className="vp-status" title={phase}>
                <i className={waiting ? "idle" : "run"} /><b>{RATE}×</b><span className="vp-phase">{phase || "Loading the machine…"}</span>
              </span>
              {waiting && ctx && <button className="vp-cta" onClick={order}><Icon name="plus" size={14} />Place an order</button>}
              <span className="vp-sep" />
              {machine.doc?.safety && (
                <button className={`vp-btn ${showCover ? "" : "off"}`} onClick={() => setShowCover(!showCover)} aria-pressed={showCover}
                  title="Show or hide the enclosure: guard frame, polycarbonate panels and doors (C)">
                  <Icon name="cube" size={15} />Enclosure
                </button>
              )}
              {machine.doc?.safety && !netZones && (
                <button className={`vp-btn ${showZones ? "on" : ""}`} onClick={() => setShowZones(!showZones)}
                  title="Show or hide the hazard zones: the swept envelopes of the moving arms" aria-pressed={showZones}>
                  <Icon name={showZones ? "eye" : "eyeoff"} size={15} />Hazard zones
                </button>
              )}
              {machine.doc?.wiring?.roles && (
                <details className="wire-legend">
                  <summary className="vp-btn"><Icon name="zap" size={15} />Wiring</summary>
                  <ul>
                    {Object.entries(machine.doc.wiring.roles).map(([k, r]) => (
                      <li key={k}>
                        <span className={`sw ${r.colour === "PE" ? "pe" : ""} ${k === "AIR" ? "air" : ""}`}
                          style={r.colour === "PE" ? undefined : { background: r.colour }} />
                        <b>{k}</b> {r.label}
                      </li>
                    ))}
                  </ul>
                </details>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
