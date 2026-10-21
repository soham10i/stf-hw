// The live cell on the Overview: the 3D twin's state machines as it bakes, over the live link.
// Nothing moves here until an order is simulated - from this card (which starts it on the open
// twin, or opens the twin with it) or in the twin itself.
import { useEffect, useRef, useState } from "react";
import { STAGES, UNITS, type UnitState } from "../shared/liveLink";
import { useTwinCamera } from "../vision/twinCamera";
import { breakNext, currentOrder, simulate, useLive } from "./live";

const STATES: UnitState[] = ["IDLE", "READY", "RUN", "HELD"];
const FLAVOUR: Record<string, string> = { chocolate: "#7a4a24", vanilla: "#efe6cf", strawberry: "#f4a6bf" };
const STAGE_SAY: Record<string, string> = {
  rack: "Rack", belt: "Belt", arm: "Robot arm", oven: "Oven", turntable: "Turntable", sorting: "Sorting", camera: "Camera", bin: "Bin",
};

/** The camera's latest frame, drawn into a canvas (the bitmap is the hook's, not ours). */
function Feed() {
  const { frame } = useTwinCamera(() => { /* photos are judged on Vision QC */ });
  const c = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const g = c.current?.getContext("2d");
    if (!g) return;
    if (frame) g.drawImage(frame.bmp, 0, 0, c.current!.width, c.current!.height);
    else g.clearRect(0, 0, c.current!.width, c.current!.height);  // the feed stopped: no stale frame
  }, [frame]);
  return (
    <figure className={`lc-cam ${frame?.lit ? "lit" : ""}`}>
      <canvas ref={c} width={160} height={160} aria-label="The inspection camera's live view" />
      {!frame && <span>camera off</span>}
      <figcaption><i className={frame ? "on" : ""} />{frame?.lit ? "photo" : "camera"}</figcaption>
    </figure>
  );
}

export function LiveCell() {
  const { state, connected, socket, notice } = useLive();
  const [broken, setBroken] = useState(false);
  const running = !!state?.running;
  const { total, done } = currentOrder(state);
  const stage = state?.cookie?.stage;
  const at = stage ? STAGES.indexOf(stage) : -1;
  return (
    <section className="db-card wide lc">
      <h3>Live cell
        <span className={`lc-link ${connected ? "on" : ""}`} title={socket ? "WebSocket /twin/live" : "this browser's tabs"}>
          <i />{connected ? (running ? "Simulating" : "Twin connected") : "No twin open"}
        </span>
      </h3>
      <div className="lc-bar">
        <button className="ui-btn primary" onClick={() => simulate(connected, broken)} disabled={running}>
          {running ? "Simulating…" : "Simulate order"}
        </button>
        <button className={`ui-btn ${broken ? "on" : ""}`} aria-pressed={broken}
          onClick={() => { const on = !broken; setBroken(on); if (running) breakNext(on); }}
          title={running ? "The next cookie comes out cracked: the camera must catch it" : "The first cookie comes out cracked: the camera must catch it"}>
          Broken cookie</button>
        <span className="lc-note">{notice ?? (connected ? "" : "Opens the 3D twin and starts there")}</span>
        {total > 0 && <span className="lc-count"><b>{done}</b>/{total} cookies</span>}
      </div>

      <div className="lc-body">
        <div className="lc-main">
          {/* the cookie's way through the cell */}
          <ol className="lc-journey" aria-label="Where the cookie is">
            {STAGES.map((s, i) => (
              <li key={s} className={i < at ? "done" : i === at ? "now" : ""}>
                <i style={i === at && state?.cookie ? { background: FLAVOUR[state.cookie.flavour] ?? "var(--accent)" } : undefined} />
                <span>{STAGE_SAY[s]}</span>
              </li>
            ))}
          </ol>
          {state?.cookie && (
            <div className="lc-cookie">
              <i style={{ background: FLAVOUR[state.cookie.flavour] }} /><b>{state.cookie.flavour}</b>
              {state.cookie.defect && <em className="bad">{state.cookie.defect}</em>}
              <span className="lc-prog"><i style={{ width: `${state.cookie.pct * 100}%` }} /></span>
              <small>{Math.round(state.cookie.pct * 100)} %</small>
            </div>
          )}
          {/* every unit's state machine */}
          <div className="lc-fsm" role="table" aria-label="Unit state machines">
            {UNITS.map((u) => {
              const s = state?.units[u] ?? { state: "IDLE" as UnitState, step: "" };
              return (
                <div key={u} className={`lc-unit ${s.state.toLowerCase()}`} role="row">
                  <b role="rowheader">{u}</b>
                  <span className="lc-states" role="cell">
                    {STATES.map((x) => <i key={x} className={x === s.state ? `on ${x.toLowerCase()}` : ""}>{x}</i>)}
                  </span>
                  <small role="cell">{s.step}</small>
                </div>
              );
            })}
          </div>
        </div>
        <aside className="lc-side">
          <Feed />
          <dl>
            <div><dt>oven</dt><dd>{state ? `${state.oven.C} °C` : "–"}{state?.oven.heating ? " · heating" : ""}</dd></div>
            <div><dt>passed</dt><dd className="ok">{state?.inspect.passed ?? "–"}</dd></div>
            <div><dt>rejected</dt><dd className={state?.inspect.rejected ? "bad" : ""}>{state?.inspect.rejected ?? "–"}</dd></div>
          </dl>
          {!!state?.inspect.recent.length && (
            <ul className="lc-ins">{state.inspect.recent.slice(0, 4).map((r) => (
              <li key={r.n} className={r.verdict === "pass" ? "ok" : "bad"}>
                <i style={{ background: FLAVOUR[r.flavour] }} />#{r.n} {r.truth === "ok" ? "good" : r.truth}<b>{r.verdict === "pass" ? "pass" : "reject"}</b>
              </li>))}</ul>
          )}
        </aside>
      </div>
    </section>
  );
}
