// The twin's shell. It owns only the view and the panel state; what the views and
// panels are lives in registry.tsx, the backend link in useBackend, the 3D machine
// in scene/HbwCad. One machine is shown: Upgrade 12, which contains U1-U11.
import { Canvas } from "@react-three/fiber";
import { useEffect, useMemo, useState } from "react";

import { HbwCadStage, RATE } from "../scene/HbwCad";
import { useCadDoc } from "../shared/model";
import { ErrorBoundary } from "../shared/ErrorBoundary";
import { Icon } from "../shared/icons";
import { usePersistent } from "../shared/persist";
import { useTheme } from "../shared/theme";
import { ComponentView, useComponents } from "../views/ComponentView";
import { ControllerView, useController } from "../views/ControllerView";
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
  const [open, setOpen] = usePersistent("stf.side.open", window.innerWidth >= 900);
  const [panelId, setPanelId] = usePersistent("stf.side.tab", "orders");
  const ctx: PanelCtx | null = machine.doc ? { doc: machine.doc, scene, showZones, setShowZones } : null;
  const panels = ctx ? PANELS.filter((p) => p.available(ctx)) : [];
  const active = panels.find((p) => p.id === panelId) ?? panels[0];
  const toggle = () => {
    setOpen(!open);
    // the Canvas remeasures on resize; some embedded browsers need the nudge
    requestAnimationFrame(() => window.dispatchEvent(new Event("resize")));
  };
  const pick = (id: string) => {
    if (open && id === active?.id) return toggle();
    if (!open) toggle();
    setPanelId(id);
  };
  const netZones = !!(open && active?.overlays?.netZones);

  return (
    <div className="app">
      <TopBar views={views} view={view} onView={setViewId} theme={theme} toggleTheme={toggleTheme}
        status={conn.conn}
        statusTip={[scene && `layout ${scene.fingerprint}`, machine.doc && `cad ${machine.doc.fingerprint}`].filter(Boolean).join("  ·  ")} />

      {view.kind === "controller" && (ctl.doc ? <ControllerView doc={ctl.doc} /> : <div className="error">{ctl.err}</div>)}
      {view.kind === "component" && comps.doc && <ComponentView id={view.id} doc={comps.doc} />}

      {view.kind === "machine" && (
        <div className="body">
          <div className="viewport">
            {apiError && <div className="error">{apiError}</div>}
            {machine.err && <div className="error">{machine.err}</div>}
            <div className="vp-tools">
              <span className="vp-pill"><Icon name="play" size={12} />{RATE}×<span className="vp-phase">{phase}</span></span>
              {machine.doc?.safety && !netZones && (
                <button className={`vp-pill btn ${showZones ? "on" : ""}`} onClick={() => setShowZones(!showZones)}
                  title="Show or hide the hazard zones: the swept envelopes of the moving arms">
                  <Icon name={showZones ? "eye" : "eyeoff"} size={14} />Hazard zones
                </button>
              )}
            </div>
            {machine.doc?.wiring?.roles && (
              <details className="wire-legend">
                <summary>Wiring colours</summary>
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
            {machine.doc && (
              <ErrorBoundary>
                <Canvas shadows dpr={[1, 2]} gl={{ preserveDrawingBuffer: true }}>
                  <HbwCadStage doc={machine.doc} onPhase={setPhase} showZones={showZones && !netZones} netZones={netZones} />
                </Canvas>
              </ErrorBoundary>
            )}
          </div>
          {ctx && active && (
            <SidePanel panels={panels} active={active} open={open} onPick={pick} onToggle={toggle} ctx={ctx} />
          )}
        </div>
      )}
    </div>
  );
}
