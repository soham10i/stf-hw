// Component health cards: one per wearing part, its health index and remaining life
// at a given machine age (health.ts), with predictive maintenance on or off.
import type { HealthComp } from "./model";
import { STATUS_TXT, compAt, spark } from "./health";

export function HealthGrid({ cs, shifts, compact = false, maintained = false }: { cs: HealthComp[]; shifts: number; compact?: boolean; maintained?: boolean }) {
  return (
    <div className={`ops-health ${compact ? "compact" : ""}`}>
      {cs.map((c) => {
        const s = compAt(c, shifts, maintained);
        return (
          <div key={c.id} className={`ops-card ${s.status}`} title={`${c.metric} · sources ${c.source.join(", ")}`}>
            <div className="ops-card-h"><b>{c.name}</b><span>{STATUS_TXT[s.status]}</span></div>
            <div className="ops-hi"><i style={{ width: `${s.hi}%` }} /><b>{Math.round(s.hi)}</b></div>
            {!compact && (
              <svg viewBox="0 0 120 26" className="ops-spark"><path d={spark(c, s.n)} /></svg>
            )}
            <div className="ops-card-f">
              <span>{Math.round(s.n).toLocaleString()} uses{s.serviced ? ` · serviced ×${s.serviced}` : ""}</span>
              <span>{s.rulShifts === null ? "–" : s.status === "fail" ? "failed" : `${s.rulShifts.toFixed(1)} shifts left`}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
