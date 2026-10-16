// The twin's two registries. Adding a view or a side panel is one entry here;
// the shell (App, TopBar, SidePanel) never names a view or a panel itself.
import type { ReactNode } from "react";
import type { CadDoc } from "../shared/model";
import type { SceneDescriptor } from "../types";
import { OrdersPanel } from "../panels/OrdersPanel";
import { TelemetryPanel } from "../panels/TelemetryPanel";
import { VcPanel } from "../panels/VcPanel";
import { IoPanel } from "../panels/IoPanel";
import { GeometryPanel } from "../panels/GeometryPanel";
import { Analysis, Connectivity, PlcTabs, SafetySecurity } from "../panels/merged";

// ---------------------------------------------------------------- views
export type ViewKind = "machine" | "controller" | "component";
export type View = { id: string; label: string; kind: ViewKind; group: string; about: string };

export const MACHINE_VIEW: View = {
  id: "factory", label: "Smart Tabletop Factory", kind: "machine", group: "Factory",
  about: "The complete machine: guarded, on remote I/O, run by the generated PLC program, "
    + "commissioned, monitored, hardened. Open the side panels for each layer.",
};
export const CONTROLLER_VIEW: View = {
  id: "controller", label: "Controller board · PLC I/O", kind: "controller", group: "Factory",
  about: "The 24 V adapter PCB and the PLC interface, pin by pin.",
};

export function componentViews(components: Record<string, { name: string; ft: string; kind?: string; upgrade?: string }> | undefined): View[] {
  return Object.entries(components ?? {}).map(([id, c]) => {
    const mech = c.kind === "mechanism";
    return {
      id, label: c.name, kind: "component" as const,
      group: mech ? "Mechanisms" : "Components",
      about: mech ? "How it works, its numbers from the model, where it is used"
        : `${/^\d+$/.test(c.ft) ? `fischertechnik ${c.ft} · ` : ""}sourced dimensions, materials, how it works`,
    };
  });
}

// --------------------------------------------------------------- panels
export type PanelCtx = {
  doc: CadDoc; scene: SceneDescriptor | null;
  showZones: boolean; setShowZones: (v: boolean) => void;
  /** the security view asks for the network zones in 3D while it is shown */
  setNetZones: (v: boolean) => void;
};
export type Panel = {
  id: string; label: string; icon: string;
  /** shown only when the export (or the live backend) has what it needs */
  available: (c: PanelCtx) => boolean;
  render: (c: PanelCtx) => ReactNode;
};

export const PANELS: Panel[] = [
  { id: "orders", label: "Orders", icon: "list", available: () => true,
    render: (c) => <OrdersPanel slots={Object.keys(c.doc.slots)} /> },
  { id: "telemetry", label: "Telemetry", icon: "activity", available: () => true,
    render: (c) => <TelemetryPanel scene={c.scene} /> },
  { id: "plc", label: "PLC", icon: "monitor", available: () => true, render: (c) => <PlcTabs c={c.doc.control} /> },
  { id: "safety", label: "Safety & security", icon: "shield", available: (c) => !!c.doc.safety,
    render: (c) => <SafetySecurity sf={c.doc.safety!} showZones={c.showZones} setShowZones={c.setShowZones} setNetZones={c.setNetZones} /> },
  { id: "io", label: "Remote I/O", icon: "plug", available: (c) => !!(c.doc.io3 && c.doc.chains),
    render: (c) => <IoPanel io={c.doc.io3!} ch={c.doc.chains!} /> },
  { id: "connectivity", label: "Connectivity", icon: "network", available: () => true, render: () => <Connectivity /> },
  { id: "vc", label: "Commissioning", icon: "cpu", available: (c) => !!c.doc.vc, render: (c) => <VcPanel vc={c.doc.vc!} /> },
  { id: "geometry", label: "Geometry", icon: "cube", available: () => true, render: (c) => <GeometryPanel doc={c.doc} /> },
  { id: "analysis", label: "Analysis", icon: "gauge", available: () => true, render: () => <Analysis /> },
];
