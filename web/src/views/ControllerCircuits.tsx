// The controller board's circuit diagrams - input, output and the bidirectional motor's relay
// pair - drawn from the extended description, with their small SVG symbols.

import { useRef, useState } from "react";

import { ControllerDoc } from "./controllerModel";


/** Two-trace scope: encoder A and B, phase-shifted a quarter period. */
export function Scope({ a, b }: { a: boolean; b: boolean }) {
  const hist = useRef<{ a: boolean[]; b: boolean[] }>({ a: [], b: [] });
  hist.current.a = [...hist.current.a, a].slice(-40);
  hist.current.b = [...hist.current.b, b].slice(-40);
  const path = (arr: boolean[], y0: number) =>
    arr.map((v, i) => `${i ? "L" : "M"}${i * 3},${y0 - (v ? 8 : 0)}`).join(" ");
  return (
    <svg viewBox="0 0 120 30" className="scope" aria-label="encoder signals">
      <path d={path(hist.current.a, 12)} /><path d={path(hist.current.b, 27)} />
    </svg>
  );
}

/** The equivalent circuits of p.35-38, redrawn. */
export function Circuits({ doc }: { doc: ControllerDoc }) {
  const [c, setC] = useState("motor");
  const tabs: [string, string][] = [["power", "Power supply"], ["switch", "Switch input"],
    ["barrier", "Light barrier"], ["encoder", "Encoder"], ["actuator", "Actuator"], ["motor", "Bidirectional motor"]];
  return (
    <section className="panel">
      <h2>Equivalent circuits <span className="clock">doc p.{doc.plc.pages.join(", ")}</span></h2>
      <div className="src-filter">
        {tabs.map(([k, l]) => <button key={k} className={c === k ? "on" : ""} onClick={() => setC(k)}>{l}</button>)}
      </div>
      <svg viewBox="0 0 520 170" className="circuit">
        {c === "power" && (<g>
          <T x={20} y={30} n="1" /><Diode x={110} y={30} /><Wire d="M40,30 H100 M130,30 H380" /><Net x={380} y={30} t="+24V Motor (relays)" />
          <T x={20} y={80} n="2" /><Diode x={110} y={80} /><Fuse x={200} y={80} t="0.2 A" /><Wire d="M40,80 H100 M130,80 H185 M225,80 H380" /><Net x={380} y={80} t="+24V Sensor" />
          <T x={20} y={125} n="3" /><T x={20} y={150} n="4" /><Wire d="M40,125 H90 V160 M40,150 H90" /><Gnd x={90} y={160} />
          <text x="150" y="140" className="note">reverse-polarity diodes; sensor rail overload-protected</text>
        </g>)}
        {c === "switch" && (<g>
          <Net x={300} y={25} t="+24V Sensor" rev /><Wire d="M300,25 H200 V60" />
          <path d="M200,60 L230,95" className="blade" /><circle cx="200" cy="100" r="3" className="dot" /><circle cx="235" cy="100" r="3" className="dot" />
          <text x="240" y="98" className="note">3 (NO)</text><text x="160" y="118" className="note">1</text>
          <Wire d="M200,100 V140 H40" /><T x={20} y={140} n="I" />
          <text x="260" y="140" className="note">closed switch → +24 V on the input (P-reading)</text>
        </g>)}
        {c === "barrier" && (<g>
          <Net x={360} y={25} t="+24V Sensor" rev /><Wire d="M360,25 H160 V55 M260,25 V70" />
          <text x="130" y="85" className="note">C</text><path d="M160,55 V75 L150,85 M150,95 L160,105 V140" className="blade" />
          <line x1="150" y1="80" x2="150" y2="100" className="blade" /><text x="120" y="118" className="note">E</text>
          <circle cx="260" cy="85" r="15" className="lamp" /><path d="M250,75 L270,95 M270,75 L250,95" className="blade" />
          <Wire d="M260,100 V150" /><Gnd x={260} y={150} /><text x="285" y="90" className="note">lamp</text>
          <Wire d="M160,140 H40" /><T x={20} y={140} n="I" />
          <text x="300" y="130" className="note">max 5 mA through the phototransistor</text>
        </g>)}
        {c === "encoder" && (<g>
          <Net x={40} y={25} t="+24V Sensor" /><Wire d="M160,25 H260 V50" />
          <rect x="235" y="50" width="50" height="30" className="box" /><text x="243" y="70" className="note">push</text>
          <Wire d="M260,80 V95 H40" /><T x={20} y={95} n="B" />
          <rect x="235" y="105" width="50" height="30" className="box" /><text x="245" y="125" className="note">pull</text>
          <Wire d="M260,95 V105 M260,135 V155" /><Gnd x={260} y={155} />
          <text x="310" y="80" className="note">quadrature A/B, 0/24 V, max 1 kHz</text>
          <text x="310" y="100" className="note">B lags A forward, leads reverse</text>
        </g>)}
        {c === "actuator" && (<g>
          <T x={20} y={50} n="Q" /><Diode x={110} y={50} /><Wire d="M40,50 H100 M130,50 H360 M220,50 V80" />
          <rect x="360" y="38" width="90" height="24" className="box" /><text x="380" y="55" className="note">lamp / valve</text>
          <g transform="translate(220,95) rotate(-90)"><Diode x={0} y={0} /></g><Wire d="M220,110 V140" /><Gnd x={220} y={140} />
          <text x="240" y="100" className="note">freewheel diode for inductive loads</text>
        </g>)}
        {c === "motor" && (<g>
          <T x={20} y={35} n="Qa" /><Diode x={90} y={35} /><Wire d="M40,35 H80 M110,35 H170" />
          <rect x="170" y="22" width="36" height="26" className="box" /><text x="176" y="40" className="note">Ra</text>
          <T x={20} y={135} n="Qb" /><Diode x={90} y={135} /><Wire d="M40,135 H80 M110,135 H170" />
          <rect x="170" y="122" width="36" height="26" className="box" /><text x="176" y="140" className="note">Rb</text>
          <Wire d="M206,35 H260 M206,135 H260" /><Fuse x={300} y={85} t="0.2 A" /><Net x={340} y={85} t="+24V Motor" />
          <Wire d="M260,35 H470 M260,135 H470 M260,35 V70 M260,135 V100 M285,85 H260" />
          <text x="480" y="38" className="note">M−</text><text x="480" y="138" className="note">M+</text>
          <Wire d="M235,85 H215" /><Gnd x={215} y={85} />
          <text x="150" y="158" className="note">each relay: lead on GND (off) or +24V Motor (on)</text>
          <text x="150" y="168" className="note">Qa only / Qb only = run either way · both = stop</text>
        </g>)}
      </svg>
    </section>
  );
}

const Wire = ({ d }: { d: string }) => <path d={d} className="w" />;
const T = ({ x, y, n }: { x: number; y: number; n: string }) => (
  <g><rect x={x} y={y - 8} width="18" height="16" className="tbox" /><text x={x - 2} y={y - 12} className="note">{n}</text></g>
);
const Diode = ({ x, y }: { x: number; y: number }) => (
  <g><path d={`M${x - 10},${y - 8} L${x - 10},${y + 8} L${x + 4},${y} Z`} className="dio" /><line x1={x + 4} y1={y - 8} x2={x + 4} y2={y + 8} className="w" /></g>
);
const Fuse = ({ x, y, t }: { x: number; y: number; t: string }) => (
  <g><rect x={x - 15} y={y - 6} width="30" height="12" className="box" /><text x={x - 12} y={y + 20} className="note">{t}</text></g>
);
const Gnd = ({ x, y }: { x: number; y: number }) => (
  <g><line x1={x - 10} y1={y} x2={x + 10} y2={y} className="w" /><line x1={x - 6} y1={y + 4} x2={x + 6} y2={y + 4} className="w" /></g>
);
const Net = ({ x, y, t, rev }: { x: number; y: number; t: string; rev?: boolean }) => (
  <g><rect x={rev ? x - 120 : x} y={y - 9} width="120" height="18" rx="2" className="net" /><text x={(rev ? x - 120 : x) + 6} y={y + 4} className="note">{t}</text></g>
);
