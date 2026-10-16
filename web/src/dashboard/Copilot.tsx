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
        <p className="hl-cap">The model calls the twin's tools (health, alarms, the month, OEE, energy, carbon, the scheduler, the inspection,
          security, the documents, the running twin) and states only what they return, with citations. The server checks every number in the
          answer against the tools; one it cannot back is flagged. When a Gemini model reaches its limit the next one answers, then a local
          model, then the tools themselves. 🔊 reads an answer aloud (Gemini TTS).</p>
      </aside>
    </div>
  );
}
