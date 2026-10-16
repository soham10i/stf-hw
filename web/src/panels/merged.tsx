// The side panels that group related views behind sub-tabs: the PLC, safety & security, and
// the Industry 4.0 connectivity, plus the Analysis panel that leads to the dashboard's pages.
import { useEffect } from "react";
import type { ControlDoc, SafetyDoc } from "../shared/model";
import { usePersistent } from "../shared/persist";
import { Icon } from "../shared/icons";
import { HmiPanel } from "./HmiPanel";
import { PlcPanel } from "./PlcPanel";
import { SafetyPanel } from "./SafetyPanel";
import { NetSecurityPanel } from "./NetSecurityPanel";
import { AasPanel } from "./AasPanel";
import { OpcuaPanel } from "./OpcuaPanel";
import { UnsPanel } from "./UnsPanel";
import { SubTabs, dashboardPage } from "./kit";

export function PlcTabs({ c }: { c?: ControlDoc }) {
  const [tab, setTab] = usePersistent<"program" | "live">("stf.side.plc", "program");
  return (
    <div className="np-tabbed">
      <SubTabs id="PLC" tabs={[["program", "Program & HMI"], ["live", "Live run"]]} value={c ? tab : "live"} onChange={setTab} />
      {c && tab === "program" ? <HmiPanel c={c} /> : <PlcPanel />}
    </div>
  );
}

export function SafetySecurity({ sf, showZones, setShowZones, setNetZones }: {
  sf: SafetyDoc; showZones: boolean; setShowZones: (v: boolean) => void; setNetZones: (v: boolean) => void;
}) {
  const [tab, setTab] = usePersistent<"safety" | "security">("stf.side.safety", "safety");
  // the 3D view shows the network zones while the security tab is open, the hazard zones otherwise
  useEffect(() => { setNetZones(tab === "security"); return () => setNetZones(false); }, [tab, setNetZones]);
  return (
    <div className="np-tabbed">
      <SubTabs id="Safety and security" tabs={[["safety", "Machine safety"], ["security", "OT security"]]} value={tab} onChange={setTab} />
      {tab === "safety" ? <SafetyPanel sf={sf} showZones={showZones} setShowZones={setShowZones} /> : <NetSecurityPanel />}
    </div>
  );
}

export function Connectivity() {
  const [tab, setTab] = usePersistent<"aas" | "opcua" | "uns">("stf.side.conn", "aas");
  return (
    <div className="np-tabbed">
      <SubTabs id="Connectivity" tabs={[["aas", "Asset shells"], ["opcua", "OPC UA"], ["uns", "Sparkplug · UNS"]]} value={tab} onChange={setTab} />
      {tab === "aas" ? <AasPanel /> : tab === "opcua" ? <OpcuaPanel /> : <UnsPanel />}
    </div>
  );
}

const ANALYSIS: [string, string, string, string][] = [
  ["health", "heart", "Health", "How worn each part is, what fails first and when"],
  ["ai", "brain", "AI maintenance", "The neural network's remaining-life predictions against the rules"],
  ["energy", "bolt", "Energy & grid", "Solar, battery and grid for a month; cost and ride-through"],
  ["throughput", "gauge", "Throughput", "Where an order's time goes and what made it faster"],
  ["hardening", "layers", "Defence in depth", "The interlocks moved into hardware, and what they cost"],
  ["vision", "eye", "Vision QC", "The inspection camera's live feed, with this twin's cookies"],
];

export function Analysis() {
  return (
    <section className="panel">
      <h2 className="np-title">Analysis</h2>
      <p className="np-lead">The machine's analytics live on the dashboard. Each opens in a new tab.</p>
      <div className="np-links">
        {ANALYSIS.map(([page, icon, title, say]) => (
          <a key={page} className="np-link" href={dashboardPage(page)} target="_blank" rel="noopener noreferrer">
            <Icon name={icon} size={18} /><span><b>{title}</b><em>{say}</em></span><Icon name="external" size={13} />
          </a>
        ))}
      </div>
    </section>
  );
}
