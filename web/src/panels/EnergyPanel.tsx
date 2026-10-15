// Upgrade 9: the cell as a microgrid (grid.py).
import { useState } from "react";
import { useJson } from "../shared/data";
import { Empty, Head, Spark, Stat } from "./kit";

type GridDoc = {
  meta: { days: number; step_h: number; assets: Record<string, number> };
  scenarios: Record<string, { total_eur: number; self_sufficiency: number; co2_kg: number; peak_w: number }>;
  series: { load: number[]; pv: number[]; grid: number[]; soc: number[] };
  power_quality: { with_ups: { survives: boolean }; grid_only: { survives: boolean } }[];
  weather: { kind: string }[];
};

export function EnergyPanel() {
  const { data: d, error: err } = useJson<GridDoc>("grid/grid.json");
  const [day, setDay] = useState(8);
  if (err) return <Empty text="No grid data: run grid.py." />;
  if (!d) return <Empty text="loading the microgrid…" />;
  const per = 24 / d.meta.step_h, sl = (a: number[]) => a.slice((day - 1) * per, day * per);
  const b = d.scenarios["pv+battery"], g = d.scenarios.grid;
  const pq = d.power_quality, ups = pq.filter((p) => p.with_ups.survives).length;
  const hi = Math.max(...sl(d.series.load), ...sl(d.series.pv), 1);
  return (
    <div className="np">
      <Head title="Microgrid" sub="PV, battery and an energy manager behind the cell" page="energy" />
      <div className="np-stats">
        <Stat label="Cost / month" value={`€${b.total_eur}`} sub={`grid only €${g.total_eur}`} tone="ok" />
        <Stat label="Self-sufficient" value={`${Math.round(b.self_sufficiency * 100)} %`} />
        <Stat label="Ride-through" value={`${ups}/${pq.length}`} sub="mains events" tone="ok" />
        <Stat label="Peak import" value={`${b.peak_w} W`} sub={`cap ${d.meta.assets.peak_cap_w} W`} tone="warn" />
      </div>
      <label className="np-slider"><span>Day</span>
        <input type="range" min={1} max={d.meta.days} value={day} onChange={(e) => setDay(+e.target.value)} /><b>{day} · {d.weather[day - 1].kind}</b></label>
      <div className="np-chart">
        <Spark ys={sl(d.series.load)} color="var(--ink)" min={0} max={hi} />
        <Spark ys={sl(d.series.pv)} color="#f2b90f" min={0} max={hi} />
        <div className="np-legend"><span><i style={{ background: "var(--ink)" }} />load</span><span><i style={{ background: "#f2b90f" }} />PV</span></div>
      </div>
      <div className="np-chart"><Spark ys={sl(d.series.soc)} color="var(--ok)" min={0} max={1} h={36} />
        <div className="np-legend"><span><i style={{ background: "var(--ok)" }} />battery charge (reserve {Math.round(d.meta.assets.reserve * 100)} %)</span></div></div>
    </div>
  );
}
