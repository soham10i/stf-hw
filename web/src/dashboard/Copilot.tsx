// Upgrade 17: the copilot's own page - the dashboard chat (Chat.tsx) at full size, with the
// machine age and maintenance setting its health answers are computed for.
import { useState } from "react";
import { Chat } from "./Chat";

export function CopilotPage({ go }: { go: (p: string) => void }) {
  const [age, setAge] = useState(140);
  const [pm, setPm] = useState(true);
  return (
    <div className="cp">
      <section className="db-card cp-chat"><Chat page="copilot" go={go} age={age} pm={pm} /></section>
      <aside className="db-card cp-side">
        <h3>Health questions use</h3>
        <label className="vq-row"><span>machine age</span><input type="range" min={0} max={420} step={10} value={age} onChange={(e) => setAge(+e.target.value)} /><b>{age} sh</b></label>
        <div className="ui-seg"><button className={pm ? "on" : ""} onClick={() => setPm(true)}>PM on</button><button className={!pm ? "on" : ""} onClick={() => setPm(false)}>PM off</button></div>
        <h3 style={{ marginTop: 18 }}>How it answers</h3>
        <p className="hl-cap">The twin's tools compute the facts (health, alarms, the month, energy, carbon, the scheduler, the inspection) and the
          documents are searched. With a Gemini key on the server, Gemini writes the answer from those facts only, with citations;
          without one, the copilot answers on its own, offline. Either way the numbers come from the twin, never from the model.</p>
      </aside>
    </div>
  );
}
