// The dashboard's chat: Gemini on the server (services/api/chat.py) when it has a key,
// grounded in what the copilot (src/copilot) computes from the twin's data, the best document
// passages and the guide to the page the operator is on; the offline copilot otherwise.
import { useEffect, useRef, useState } from "react";
import { loadJson } from "../shared/data";
import { HAS_API } from "../shared/mode";
import { DATA, EXAMPLES, answer, ground, type Answer, type Ctx, type DataKey } from "../copilot/copilot";
import { GUIDE } from "./guide";

type Reply = { text: string; via: "gemini" | "offline"; model?: string; note?: string; local: Answer };
type Msg = { q: string; r: Reply | null; ms?: number };
type Status = { enabled: boolean; model: string | null };

let statusP: Promise<Status> | null = null;
function llmStatus(): Promise<Status> {
  if (!HAS_API) return Promise.resolve({ enabled: false, model: null });
  statusP ??= fetch("/chat/status").then((r) => (r.ok ? r.json() : { enabled: false, model: null })).catch(() => ({ enabled: false, model: null }));
  return statusP;
}

/** Minimal markdown for the model's replies: paragraphs, "- " lists, **bold**, [citations]. */
function Md({ text }: { text: string }) {
  const inline = (s: string) => s.split(/(\*\*[^*]+\*\*|\[[^\]]+\])/g).map((p, i) =>
    p.startsWith("**") ? <b key={i}>{p.slice(2, -2)}</b> : p.startsWith("[") ? <span key={i} className="ch-cite">{p}</span> : p);
  const blocks: JSX.Element[] = [];
  let list: string[] = [];
  const flush = () => { if (list.length) { blocks.push(<ul key={blocks.length}>{list.map((l, i) => <li key={i}>{inline(l)}</li>)}</ul>); list = []; } };
  for (const line of text.split("\n")) {
    const m = /^\s*[-*•]\s+(.*)$/.exec(line);
    if (m) list.push(m[1]);
    else { flush(); if (line.trim()) blocks.push(<p key={blocks.length}>{inline(line)}</p>); }
  }
  flush();
  return <>{blocks}</>;
}

export function Chat({ page, go, age, pm, compact = false }: { page: string; go: (p: string) => void; age: number; pm: boolean; compact?: boolean }) {
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [q, setQ] = useState("");
  const [status, setStatus] = useState<Status>({ enabled: false, model: null });
  const [useLlm, setUseLlm] = useState(true);
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => { llmStatus().then(setStatus); }, []);
  useEffect(() => { end.current?.scrollIntoView({ block: "nearest" }); }, [msgs]);
  const llm = status.enabled && useLlm;

  const ask = async (text: string) => {
    const t = text.trim();
    if (!t) return;
    setQ("");
    const history = msgs.slice(-3).flatMap((m) => (m.r ? [{ role: "user", text: m.q }, { role: "assistant", text: m.r.text.slice(0, 1500) }] : []));
    setMsgs((m) => [...m, { q: t, r: null }]);
    const ctx: Ctx = { age, pm, get: <T,>(k: DataKey) => loadJson<T>(DATA[k]) };
    const t0 = performance.now();
    let r: Reply;
    try {
      if (!llm) {
        const local = await answer(t, ctx);
        r = { text: local.text, via: "offline", local };
      } else {
        const { local, passages } = await ground(t, ctx);
        const g = GUIDE[page];
        const guide = g ? `Dashboard page "${g.title}": ${g.what} How to read it: ${g.read.join(" ")} Sections: ${g.sections.map(([k, v]) => `${k}: ${v}`).join(" ")}` : "";
        const res = await fetch("/chat", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            question: t, page: g?.title ?? page, history,
            grounding: {
              tool: local.tool === "documents" ? "none" : local.tool, text: local.text.slice(0, 2900),
              facts: (local.facts ?? []).slice(0, 20).map(([k, v]) => [k, String(v)]),
              sources: [...local.sources, ...passages.map((h) => `${h.p.doc} > ${h.p.path.filter(Boolean).slice(-1)[0] ?? ""}`)].slice(0, 6),
              passages: [guide, ...passages.map((h) => `[${h.p.doc} > ${h.p.path.filter(Boolean).slice(-1)[0] ?? ""}] ${h.p.text}`)].filter(Boolean).slice(0, 4).map((x) => x.slice(0, 1800)),
            },
          }),
        });
        const body = await res.json().catch(() => ({}));
        r = res.ok ? { text: body.answer, via: "gemini", model: body.model, local }
          : { text: local.text, via: "offline", local, note: `Gemini unavailable (${body.detail ?? res.status}); answered offline.` };
      }
    } catch (e) {
      r = { text: `Could not answer: ${(e as Error).message}`, via: "offline", local: { tool: "none", text: "", sources: [] } };
    }
    setMsgs((m) => m.map((x, i) => (i === m.length - 1 ? { ...x, r, ms: performance.now() - t0 } : x)));
  };

  return (
    <div className={`ch ${compact ? "compact" : ""}`}>
      <div className="ch-mode">
        {status.enabled ? (
          <div className="ui-seg"><button className={useLlm ? "on" : ""} onClick={() => setUseLlm(true)}>Gemini</button>
            <button className={!useLlm ? "on" : ""} onClick={() => setUseLlm(false)}>offline</button></div>
        ) : <span className="db-muted">offline copilot{HAS_API ? " · set GEMINI_API_KEY on the server for the LLM" : ""}</span>}
        {llm && <em>{status.model} · answers only from the twin's data</em>}
      </div>
      <div className="cp-log">
        {msgs.length === 0 && (
          <div className="cp-empty">
            <b>Ask about {GUIDE[page] ? `“${GUIDE[page].title}”` : "the cell"}.</b>
            <span>{llm ? "Gemini explains, using only the twin's own numbers and documents." : "Answers come from the twin's data or its documents, with the source."}</span>
            <div className="cp-ex row">{(compact ? ["What does this page show?", ...EXAMPLES.slice(0, 3)] : EXAMPLES).map((e) => <button key={e} onClick={() => ask(e)}>{e}</button>)}</div>
          </div>
        )}
        {msgs.map((m, i) => (
          <div key={i} className="cp-turn">
            <div className="cp-q">{m.q}</div>
            {m.r ? (
              <div className={`cp-a ${m.r.local.tool === "none" && m.r.via === "offline" ? "none" : ""}`}>
                {m.r.via === "gemini" ? <div className="ch-md"><Md text={m.r.text} /></div> : <p>{m.r.text}</p>}
                {m.r.via === "offline" && m.r.local.facts && <dl className="cp-facts">{m.r.local.facts.map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}</dl>}
                {m.r.note && <p className="ch-note">{m.r.note}</p>}
                <div className="cp-src">
                  {m.r.local.link && <button className="db-link" onClick={() => go(m.r!.local.link!.page)}>open {m.r.local.link.label} →</button>}
                  {m.r.local.sources.length > 0 && <span>grounded in: {m.r.local.sources[0]}</span>}
                  <em>{m.r.via === "gemini" ? m.r.model : m.r.local.tool === "documents" ? "documents" : m.r.local.tool === "none" ? "" : `tool: ${m.r.local.tool}`}{m.ms !== undefined ? ` · ${(m.ms / 1000).toFixed(1)} s` : ""}</em>
                </div>
              </div>
            ) : <div className="cp-a"><p className="db-muted">{llm ? "asking Gemini…" : "…"}</p></div>}
          </div>
        ))}
        <div ref={end} />
      </div>
      <form className="cp-ask" onSubmit={(e) => { e.preventDefault(); ask(q); }}>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={compact ? "Ask about this page…" : "e.g. why did the line stop this month?"} aria-label="Question" />
        <button className="ui-btn" type="submit" disabled={!q.trim()}>Ask</button>
      </form>
    </div>
  );
}
