// The Test bench: a module of the factory run by the physics engine instead of the animation.
//   Sorting line     cookies on a moving belt, pneumatic ejectors, light barriers
//   Warehouse axes   DC encoder motors on spindles, reference switches, the PLC's positioning;
//                    the belt on its S-motor between two light barriers
//   Robot arm        the gripper's swivel, plunge and reach on encoder motors
// The physics runs in a worker at 100 Hz (scene/bench/benchStore.ts); this panel only sends
// commands and shows what it reads.
import type { CadDoc } from "../shared/model";
import { Icon } from "../shared/icons";
import {
  addCookie, addMould, armTo, axis, chooseModule, eject, homeAll, pauseBench, setBeltSpeed, setRate, startBench, stopBench, useBench,
  type AxisReading, type BenchView,
} from "../scene/bench/benchStore";
import { COLOURS, PUSHER, type Colour } from "../scene/bench/sortingWorld";
import { BELT_MM_S, BRAKE_LEAD, DRUM_D_MM, PULSES_PER_REV, SPINDLE_LEAD_MM, type CraneAxis } from "../scene/bench/warehouseWorld";
import { PLUNGE_MASS_KG, SWIVEL_CREEP_V, SWIVEL_DEG_PER_REV } from "../scene/bench/vgrWorld";
import { Note } from "./kit";

const FLAVOUR: Record<Colour, string> = { weiss: "Vanilla", rot: "Strawberry", blau: "Chocolate" };
const BAY: Record<Colour, string> = { weiss: "I5", rot: "I6", blau: "I7" };
const RATES = [1, 2, 4, 8];

export function BenchPanel({ doc }: { doc: CadDoc }) {
  const b = useBench();
  const on = b.status === "running" || b.status === "paused";
  return (
    <section className="panel bench">
      <div className="ui-seg bench-modules" role="tablist" aria-label="Module">
        <button role="tab" aria-selected={b.module === "sorting"} className={b.module === "sorting" ? "on" : ""} onClick={() => chooseModule("sorting")}>Sorting line</button>
        <button role="tab" aria-selected={b.module === "warehouse"} className={b.module === "warehouse" ? "on" : ""} onClick={() => chooseModule("warehouse")}>Warehouse</button>
        <button role="tab" aria-selected={b.module === "arm"} className={b.module === "arm" ? "on" : ""} onClick={() => chooseModule("arm")}>Robot arm</button>
      </div>
      <p className="sf-line">
        {b.module === "sorting"
          ? "Cookies on a moving belt, pneumatic ejectors, light barriers - real physics."
          : b.module === "warehouse"
            ? "The crane's motors, spindles and reference switches, driven by the PLC's positioning, and its belt."
            : "The gripper's swivel, plunge and reach: encoder motors, reference switches, the PLC's positioning."}
      </p>

      <div className="bench-run">
        {!on ? (
          <button className="ui-btn primary" disabled={b.status === "starting"} onClick={() => void startBench(doc)}>
            <Icon name="play" size={14} />{b.status === "starting" ? "Loading the physics engine…" : "Start the bench"}
          </button>
        ) : (
          <>
            <button className="ui-btn" onClick={() => pauseBench(b.status === "running")}>
              <Icon name={b.status === "running" ? "pause" : "play"} size={14} />{b.status === "running" ? "Pause" : "Resume"}
            </button>
            <button className="ui-btn" onClick={stopBench}><Icon name="stop" size={14} />Stop</button>
            <div className="ui-seg" role="radiogroup" aria-label="Speed" title="Faster than real time: more 10 ms steps a second, the same physics">
              {RATES.map((r) => <button key={r} role="radio" aria-checked={b.rate === r} className={b.rate === r ? "on" : ""} onClick={() => setRate(r)}>{r}×</button>)}
            </div>
          </>
        )}
      </div>
      {b.error && <p className="np-err">{b.error}</p>}

      {on && b.module === "sorting" && <Sorting b={b} />}
      {on && b.module === "warehouse" && <Warehouse b={b} doc={doc} />}
      {on && b.module === "arm" && <Arm b={b} doc={doc} />}

      {on && (
        <p className="bench-stats mono">
          t {b.simTime.toFixed(2)} s
          {b.stats && <> · {b.stats.stepsPerSecond.toFixed(0)} steps/s · {b.stats.stepMsMean.toFixed(2)} ms/step</>}
        </p>
      )}
    </section>
  );
}

function Sorting({ b }: { b: BenchView }) {
  return (
    <>
      <h3>Add a cookie <em className="sf-std">at the inlet · {b.cookies} on the bench</em></h3>
      <div className="bench-row">
        {COLOURS.map((c) => <button key={c} className="ui-btn" onClick={() => addCookie(c)}>{FLAVOUR[c]}</button>)}
      </div>

      <h3>Ejectors <em className="sf-std">{PUSHER.stroke_mm} mm stroke · up to {PUSHER.vmax} mm/s</em></h3>
      <div className="bench-row">
        {COLOURS.map((c) => (
          <button key={c} className="ui-btn" onClick={() => eject(c)} title={`Fire the ${FLAVOUR[c].toLowerCase()} ejector: out, hold 0.15 s, back`}>
            {FLAVOUR[c]} <span className="mono">{b.strokes[c]} mm</span>
          </button>
        ))}
      </div>

      <h3>Belt <em className="sf-std mono">{b.beltSpeed} mm/s</em></h3>
      <input type="range" min={0} max={120} step={5} value={b.beltSpeed} aria-label="Belt speed"
        onChange={(e) => setBeltSpeed(Number(e.target.value))} className="bench-slider" />

      <h3>Live readings</h3>
      <ul className="sf-rows bench-readings">
        {(["I2", "I3"] as const).map((t) => (
          <li key={t}><i className={`bench-led ${b.barriers[t] ? "on" : ""}`} /><b>{t}</b><span>{t === "I2" ? "inlet barrier" : "after the colour sensor"}</span><em>{b.barriers[t] ? "cut" : "clear"}</em></li>
        ))}
        {COLOURS.map((c) => (
          <li key={c}><i className={`bench-led ${b.barriers[BAY[c] as "I5"] ? "on" : ""}`} /><b>{BAY[c]}</b><span>{FLAVOUR[c].toLowerCase()} bay</span><em>{b.barriers[BAY[c] as "I5"] ? "cookie in" : "empty"}</em></li>
        ))}
      </ul>

      <Note title="Try this">
        <ul>
          <li>Add a cookie, and fire its ejector as it reaches the pusher: it is pushed off the belt into the bay, and the bay's barrier sees it.</li>
          <li>Fire too early or too late: the pusher misses, or knocks the cookie along the belt.</li>
          <li>Speed the belt up: the ejector has less time, as on the real line.</li>
        </ul>
      </Note>
      <Note title="How it is simulated">
        Rapier {b.rapier} in a worker thread at a fixed 100 Hz, in millimetres; the twin draws what it publishes
        through {b.shared ? "shared memory" : "a copied buffer (this host cannot share memory)"}. The parts are the CAD
        export's own boxes. The belt carries what lies on it, limited by friction; the ejectors accelerate, cruise and
        brake to their stroke; each barrier's beam is a thin volume from its transmitter to its receiver.
      </Note>
    </>
  );
}

const MM_PER_COUNT = SPINDLE_LEAD_MM / PULSES_PER_REV;
const counts = (n: number) => `${n} count${Math.abs(n) === 1 ? "" : "s"}`;
const fmt = (v: number, d = 2) => (Number.isFinite(v) ? v.toFixed(d) : "–");

function Warehouse({ b, doc }: { b: BenchView; doc: CadDoc }) {
  const stops = doc.joints as unknown as Record<CraneAxis, { stops: Record<string, number> }>;
  const ax = b.axes;
  return (
    <>
      <div className="bench-row">
        <button className="ui-btn primary" onClick={homeAll} title="The fork back to I6, the lift up to I4, the travel to I1 - each zeroes its count there">
          <Icon name="home" size={14} />Home all
        </button>
      </div>

      {(["travel", "lift"] as const).map((id) => (
        <AxisCard key={id} id={id} label={id === "travel" ? "Travel" : "Lift"} r={ax?.[id]} stops={stops[id].stops} unit="mm" perCount={MM_PER_COUNT} />
      ))}

      <h3>Fork <em className="sf-std">no encoder: by its switches</em></h3>
      <div className="bench-row">
        <button className="ui-btn" onClick={() => axis("fork", { kind: "until", dir: 1, switch: 1 })}>Into the shelf <span className="mono">→ I5</span></button>
        <button className="ui-btn" onClick={() => axis("fork", { kind: "until", dir: -1, switch: 0 })}>Back <span className="mono">→ I6</span></button>
        <button className="ui-btn" onClick={() => axis("fork", { kind: "stop" })}>Stop</button>
      </div>
      {ax && <p className="bench-axis-line mono">{fmt(ax.fork.position, 1)} mm · {fmt(ax.fork.rpm, 0)} rpm · {fmt(ax.fork.current * 1000, 0)} mA · {ax.fork.task}</p>}

      <h3>Belt <em className="sf-std">M1 · S-motor · {b.moulds} mould{b.moulds === 1 ? "" : "s"} on it</em></h3>
      <div className="bench-row">
        <button className="ui-btn" onClick={addMould} title="A mould set down where the crane hands over">Add a mould</button>
        <button className="ui-btn" onClick={() => axis("belt", { kind: "until", dir: 1, switch: 1 })}>Out <span className="mono">→ I3</span></button>
        <button className="ui-btn" onClick={() => axis("belt", { kind: "until", dir: -1, switch: 0 })}>In <span className="mono">→ I2</span></button>
        <button className="ui-btn" onClick={() => axis("belt", { kind: "stop" })}>Stop</button>
      </div>
      {ax && <p className="bench-axis-line mono">{fmt((ax.belt.rpm * Math.PI * DRUM_D_MM) / 60, 1)} mm/s · {fmt(ax.belt.rpm, 0)} rpm · {fmt(ax.belt.current * 1000, 0)} mA · {ax.belt.task}</p>}

      <Switches b={b} rows={[["I1", "travel reference, at the conveyor"], ["I4", "lift reference, at the top"], ["I5", "fork front"], ["I6", "fork back"], ["I2", "light barrier inside, at the crane"], ["I3", "light barrier outside, at the gripper"]]} />

      <Note title="Try this">
        <ul>
          <li>Move an axis before homing it: the PLC refuses - it does not know where it is yet.</li>
          <li>Home all, then send the crane to a bay: it travels at 14.27 mm/s and stops within two encoder counts (0.11 mm), most often within one.</li>
          <li>Watch the lift: it is a little slower up than down, against the carriage's weight.</li>
          <li>Jog the travel past I1: it runs into the end of the rail, a crash.</li>
          <li>Add a mould and send it out: the belt stops as the mould cuts I3, then coasts a little.</li>
        </ul>
      </Note>
      <Note title="How it is simulated">
        Each axis is the fischertechnik 24 V encoder motor on a {SPINDLE_LEAD_MM} mm spindle, from its datasheet: 440 rpm
        with no load, 1800 g·cm stall torque, 0.60 A. The spindle's friction is set so the axis runs at the lab-calibrated
        214 rpm (14.27 mm/s, 320 mA). The motor's speed follows its exact solution between steps, it brakes when the relays
        short its leads, and the spindle holds the lift against gravity. The encoder counts {PULSES_PER_REV} pulses a turn
        ({fmt(1 / MM_PER_COUNT, 2)} per mm). The positioning block switches the motor off {BRAKE_LEAD} counts early, and
        homing zeroes the count where the reference switch closes. The belt is the S-motor (165 rpm through its
        64.8:1 gearbox) on a {DRUM_D_MM} mm drum; its load is set so it runs at the project's {BELT_MM_S} mm/s [assumed],
        and it carries what lies on it by friction.
      </Note>
    </>
  );
}

function Switches({ b, rows }: { b: BenchView; rows: [string, string][] }) {
  return (
    <>
      <h3>Switches</h3>
      <ul className="sf-rows bench-readings">
        {rows.map(([t, what]) => {
          const beam = what.startsWith("light");
          return <li key={t}><i className={`bench-led ${b.switches[t] ? "on" : ""}`} /><b>{t}</b><span>{what}</span><em>{b.switches[t] ? (beam ? "cut" : "closed") : (beam ? "clear" : "open")}</em></li>;
        })}
      </ul>
    </>
  );
}

const STATIONS: [string, string][] = [["belt", "Belt hand-over"], ["oven", "Oven"], ["bay_weiss", "Vanilla bay"], ["bay_rot", "Strawberry bay"], ["bay_blau", "Chocolate bay"]];
const DEG_PER_COUNT = SWIVEL_DEG_PER_REV / PULSES_PER_REV;

function Arm({ b, doc }: { b: BenchView; doc: CadDoc }) {
  const J = (doc.vgr as unknown as { joints: Record<string, { stops: Record<string, number> }> }).joints;
  const ax = b.axes;
  return (
    <>
      <div className="bench-row">
        <button className="ui-btn primary" onClick={homeAll} title="The plunge up to I1, the reach back to I2, the swivel onto I3 - each zeroes its count there">
          <Icon name="home" size={14} />Home all
        </button>
        <select className="ui-select" aria-label="Station" defaultValue=""
          onChange={(e) => { if (e.target.value) armTo(e.target.value); e.target.value = ""; }}>
          <option value="" disabled>Go to a station…</option>
          {STATIONS.map(([k, name]) => <option key={k} value={k}>{name}</option>)}
        </select>
      </div>
      <AxisCard id="swivel" label="Swivel" r={ax?.swivel} stops={J.swivel.stops} unit="deg" perCount={DEG_PER_COUNT} />
      <AxisCard id="plunge" label="Plunge" r={ax?.plunge} stops={J.plunge.stops} unit="mm" perCount={MM_PER_COUNT} />
      <AxisCard id="reach" label="Reach" r={ax?.reach} stops={J.reach.stops} unit="mm" perCount={MM_PER_COUNT} />
      <Switches b={b} rows={[["I3", "swivel reference, a cam on the ring"], ["I1", "plunge reference, at the top"], ["I2", "reach reference, drawn back"]]} />
      <Note title="Try this">
        <ul>
          <li>Home all, then go to the belt hand-over: the swivel and the reach move together and each stops within two counts, most often one.</li>
          <li>Compare the counts: a swivel count is {fmt(DEG_PER_COUNT, 3)}° - 1.6 mm where the cup meets the belt - a spindle count 0.053 mm.</li>
          <li>Home the swivel from above 0° (where it powers up): it leaves the cam first, then comes back onto it slowly.</li>
        </ul>
      </Note>
      <Note title="How it is simulated">
        Three fischertechnik encoder motors as in the warehouse. Plunge and reach run on {SPINDLE_LEAD_MM} mm spindles;
        the plunge lifts {PLUNGE_MASS_KG} kg [assumed]. The swivel's gearing is not documented: {fmt(SWIVEL_DEG_PER_REV, 1)}° a
        motor turn [assumed] gives the kernel's 60°/s. It homes twice, the second time at {SWIVEL_CREEP_V} V, since at full speed
        one 10 ms scan is 0.6° - 4 mm at the belt. The stations are the CAD's own solved poses.
      </Note>
    </>
  );
}

function AxisCard({ id, label, r, stops, unit, perCount }: {
  id: string; label: string; r: AxisReading | undefined; stops: Record<string, number>; unit: "mm" | "deg"; perCount: number;
}) {
  const u = unit === "deg" ? "°" : " mm";
  return (
    <>
      <h3>{label} <em className="sf-std">{r?.homed ? "homed" : "not homed"}</em></h3>
      <div className="bench-row">
        <select className="ui-select" aria-label={`${id} position`} defaultValue=""
          onChange={(e) => { if (e.target.value) axis(id, { kind: "move", target: Number(e.target.value) }); e.target.value = ""; }}>
          <option value="" disabled>Move to…</option>
          {Object.entries(stops).map(([name, val]) => <option key={name} value={val}>{name} · {val}{u}</option>)}
        </select>
        <button className="ui-btn icon" aria-label={`Jog ${id} down`} title="Jog (until Stop)" onClick={() => axis(id, { kind: "jog", dir: -1 })}>−</button>
        <button className="ui-btn icon" aria-label={`Jog ${id} up`} title="Jog (until Stop)" onClick={() => axis(id, { kind: "jog", dir: 1 })}>+</button>
        <button className="ui-btn" onClick={() => axis(id, { kind: "stop" })}>Stop</button>
        <button className="ui-btn" onClick={() => axis(id, { kind: "home" })}>Home</button>
      </div>
      {r && (
        <dl className="bench-axis">
          <dt>position</dt><dd className="mono">{fmt(r.position, unit === "deg" ? 3 : 2)}{u}</dd>
          <dt>encoder</dt><dd className="mono">{r.homed ? counts(r.count) : "–"}</dd>
          <dt>speed</dt><dd className="mono">{fmt(r.rpm, 0)} rpm · {fmt(Math.abs(r.rpm) * (perCount * PULSES_PER_REV) / 60, unit === "deg" ? 1 : 2)}{unit === "deg" ? "°/s" : " mm/s"}</dd>
          <dt>current</dt><dd className="mono">{fmt(r.current * 1000, 0)} mA</dd>
          <dt>task</dt><dd>{r.task}{r.crashes ? ` · ${r.crashes} crash${r.crashes > 1 ? "es" : ""}` : ""}</dd>
          <dt>last stop</dt><dd className="mono">{Number.isFinite(r.error) ? `${r.error >= 0 ? "+" : ""}${fmt(r.error, 3)}${u} (${counts(Math.round(r.error / perCount))})` : "–"}</dd>
        </dl>
      )}
    </>
  );
}
