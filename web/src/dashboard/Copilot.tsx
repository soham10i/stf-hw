// Upgrade 17: the operator copilot (src/copilot/copilot.ts). Ask about the cell in plain
// words; the answer is computed from the twin's data or quoted from its documents, always
// with its source - and "I don't know" when nothing covers the question.
import { useEffect, useRef, useState } from "react";
import { loadJson } from "../shared/data";
import { DATA, EXAMPLES, answer, type Answer, type Ctx, type DataKey } from "../copilot/copilot";

type Msg = { q: string; a: Answer | null; ms?: number };

export function CopilotPage({ go }: { go: (p: string) => void }) {
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [q, setQ] = useState("");
  const [age, setAge] = useState(140);
  const [pm, setPm] = useState(true);
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => { end.current?.scrollIntoView({ block: "nearest" }); }, [msgs]);
  const ask = async (text: string) => {
    const t = text.trim();
    if (!t) return;
    setQ("");
    setMsgs((m) => [...m, { q: t, a: null }]);
    const ctx: Ctx = { age, pm, get: <T,>(k: DataKey) => loadJson<T>(DATA[k]) };
    const t0 = performance.now();
    let a: Answer;
    try { a = await answer(t, ctx); } catch (e) { a = { tool: "none", text: `Could not load the data: ${(e as Error).message}`, sources: [] }; }
    setMsgs((m) => m.map((x, i) => (i === m.length - 1 ? { ...x, a, ms: performance.now() - t0 } : x)));
  };
  return (
    <div className="cp">
      <section className="db-card cp-chat">
        <div className="cp-log">
          {msgs.length === 0 && (
            <div className="cp-empty">
              <b>Ask about the cell.</b>
              <span>Answers come from the twin's data or its documents, with the source — never guessed.</span>
            </div>
          )}
          {msgs.map((m, i) => (
            <div key={i} className="cp-turn">
              <div className="cp-q">{m.q}</div>
              {m.a ? (
                <div className={`cp-a ${m.a.tool === "none" ? "none" : ""}`}>
                  <p>{m.a.text}</p>
                  {m.a.facts && <dl className="cp-facts">{m.a.facts.map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}</dl>}
                  {m.a.passages && m.a.passages.length > 1 && (
                    <details className="cp-more"><summary>{m.a.passages.length - 1} more passage{m.a.passages.length > 2 ? "s" : ""}</summary>
                      {m.a.passages.slice(1).map((h) => <p key={h.p.id}><b>{h.p.doc} › {h.p.path.filter(Boolean).slice(-1)[0]}</b> {h.p.text.slice(0, 260)}…</p>)}</details>
                  )}
                  <div className="cp-src">
                    {m.a.link && <button className="db-link" onClick={() => go(m.a!.link!.page)}>open {m.a.link.label} →</button>}
                    {m.a.sources.length > 0 && <span>source: {m.a.sources[0]}</span>}
                    <em>{m.a.tool === "documents" ? "from the documents" : m.a.tool === "none" ? "" : `tool: ${m.a.tool}`}{m.ms !== undefined ? ` · ${Math.round(m.ms)} ms` : ""}</em>
                  </div>
                </div>
              ) : <div className="cp-a"><p className="db-muted">…</p></div>}
            </div>
          ))}
          <div ref={end} />
        </div>
        <form className="cp-ask" onSubmit={(e) => { e.preventDefault(); ask(q); }}>
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="e.g. when will the suction cup fail?" aria-label="Question" />
          <button className="ui-btn" type="submit" disabled={!q.trim()}>Ask</button>
        </form>
      </section>
      <aside className="db-card cp-side">
        <h3>Try</h3>
        <div className="cp-ex">{EXAMPLES.map((e) => <button key={e} onClick={() => ask(e)}>{e}</button>)}</div>
        <h3>Health questions use</h3>
        <label className="vq-row"><span>machine age</span><input type="range" min={0} max={420} step={10} value={age} onChange={(e) => setAge(+e.target.value)} /><b>{age} sh</b></label>
        <div className="ui-seg"><button className={pm ? "on" : ""} onClick={() => setPm(true)}>PM on</button><button className={!pm ? "on" : ""} onClick={() => setPm(false)}>PM off</button></div>
        <p className="hl-cap">No language model: questions are routed to tools that compute from the twin's data, or matched to passages of the documents (BM25). It runs in the page, free and offline.</p>
      </aside>
    </div>
  );
}
