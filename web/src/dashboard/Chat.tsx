// The dashboard's chat: Gemini on the server (services/api/chat.py) when it has a key,
// grounded in what the copilot (src/copilot) computes from the twin's data, the best document
// passages and the guide to the page the operator is on; the offline copilot otherwise.
import { useEffect, useRef, useState } from "react";
import { loadJson } from "../shared/data";
import { HAS_API } from "../shared/mode";
import { DATA, EXAMPLES, answer, type Ctx, type DataKey } from "../copilot/copilot";
import { GUIDE } from "./guide";

type Reply = {
  text: string; via: "gemini" | "ollama" | "rules" | "offline"; model?: string; note?: string;
  sources?: string[]; links?: { page: string; label: string }[]; tools?: string[];
  /** numbers in the answer that the twin's data does not back (the server's check) */
  unverified?: string[];
};
type Msg = { q: string; r: Reply | null; ms?: number };
type Status = {
  enabled: boolean;
  model: string | null;
  gemini?: boolean;
  ollama?: boolean;
  gemini_model?: string | null;
  ollama_model?: string | null;
};

async function llmStatus(): Promise<Status> {
  if (!HAS_API) return { enabled: false, model: null };
  try {
    const r = await fetch("/chat/status");
    if (r.ok) return await r.json();
  } catch {}
  return { enabled: false, model: null };
}

/** Minimal markdown for the model's replies: paragraphs, "- " lists, **bold**, [citations]. */
function Md({ text }: { text: string }) {
  const inline = (s: string) => s.split(/(\*\*[^*]+\*\*|\[[^\]]+\])/g).map((p, i) =>
    p.startsWith("**") ? <b key={i}>{p.slice(2, -2)}</b> : p.startsWith("[") ? <span key={i} className="ch-cite">{p}</span> : p);
  const blocks: JSX.Element[] = [];
  let list: string[] = [];
  const flush = () => { if (list.length) { blocks.push(<ul key={blocks.length}>{list.map((l, i) => <li key={i}>{inline(l)}</li>)}</ul>); list = []; } };
  for (const line of text.split("\n")) {
    const h = /^\s*(#{1,4})\s+(.*)$/.exec(line);
    const hr = /^\s*[-*_]{3,}\s*$/.test(line);
    const m = /^\s*[-*•]\s+(.*)$/.exec(line);
    if (h) {
      flush();
      blocks.push(<h4 key={blocks.length} style={{ margin: "8px 0 4px", fontSize: "0.95em", fontWeight: 600 }}>{inline(h[2])}</h4>);
    } else if (hr) {
      flush();
      blocks.push(<hr key={blocks.length} style={{ opacity: 0.2, margin: "8px 0" }} />);
    } else if (m) {
      list.push(m[1]);
    } else {
      flush();
      if (line.trim()) blocks.push(<p key={blocks.length}>{inline(line)}</p>);
    }
  }
  flush();
  return <>{blocks}</>;
}

/** Reads an answer aloud: the server's Gemini voice (2.5 Pro TTS, a flash voice when its quota
    is closed), or the browser's own voice when the server has none. Click again to stop. */
function Speak({ text }: { text: string }) {
  const [state, setState] = useState<"idle" | "loading" | "playing">("idle");
  const [by, setBy] = useState<string | null>(null);
  const audio = useRef<HTMLAudioElement | null>(null);
  const stop = () => {
    audio.current?.pause();
    audio.current = null;
    window.speechSynthesis?.cancel();
    setState("idle");
  };
  useEffect(() => stop, []);
  const browserVoice = () => {
    if (!window.speechSynthesis) { setState("idle"); return; }
    const u = new SpeechSynthesisUtterance(text.replace(/\[[^\]]{1,120}\]|[*_`#>]/g, ""));
    u.onend = () => setState("idle");
    setBy("browser voice");
    setState("playing");
    window.speechSynthesis.speak(u);
  };
  const play = async () => {
    if (state !== "idle") return stop();
    setState("loading");
    if (!HAS_API) return browserVoice();
    try {
      const r = await fetch("/chat/tts", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }) });
      if (!r.ok) return browserVoice();
      setBy(r.headers.get("X-TTS-Model"));
      const a = new Audio(URL.createObjectURL(await r.blob()));
      audio.current = a;
      a.onended = () => { URL.revokeObjectURL(a.src); setState("idle"); };
      setState("playing");
      await a.play();
    } catch {
      browserVoice();
    }
  };
  return (
    <button className={`ch-speak ${state}`} onClick={play} title={state === "idle" ? "Read the answer aloud" : "Stop"}
      aria-label={state === "idle" ? "Read the answer aloud" : "Stop reading"}>
      {state === "loading" ? "…" : state === "playing" ? "■" : "🔊"}
      {state === "playing" && by && <span>{by}</span>}
    </button>
  );
}

export function Chat({ page, go, age, pm, compact = false }: { page: string; go: (p: string) => void; age: number; pm: boolean; compact?: boolean }) {
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [q, setQ] = useState("");
  const [status, setStatus] = useState<Status>({ enabled: false, model: null });
  const [mode, setMode] = useState<"gemini" | "ollama" | "rules">("gemini");
  const end = useRef<HTMLDivElement>(null);

  useEffect(() => {
    llmStatus().then((s) => {
      setStatus(s);
      if (s.gemini) setMode("gemini");
      else if (s.ollama) setMode("ollama");
      else setMode("rules");
    });
  }, []);

  useEffect(() => { end.current?.scrollIntoView({ block: "nearest" }); }, [msgs]);

  const ask = async (text: string) => {
    const t = text.trim();
    if (!t) return;
    setQ("");
    const history = msgs.slice(-3).flatMap((m) => (m.r ? [{ role: "user", text: m.q }, { role: "assistant", text: m.r.text.slice(0, 1500) }] : []));
    setMsgs((m) => [...m, { q: t, r: null }]);
    const t0 = performance.now();
    let r: Reply;
    try {
      if (!HAS_API) {
        const ctx: Ctx = { age, pm, get: <T,>(k: DataKey) => loadJson<T>(DATA[k]) };
        const local = await answer(t, ctx);
        r = { text: local.text, via: "offline", sources: local.sources, links: local.link ? [local.link] : [] };
      } else {
        const res = await fetch("/chat", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ question: t, page, history, provider: mode, age, pm }),
        });
        const body = await res.json().catch(() => ({}));
        if (res.ok) {
          // the server answers from the twin's tools itself when the model is unavailable (body.note says so)
          r = { text: body.answer, via: body.model === "rules" ? "rules" : mode, model: body.model, note: body.note,
                sources: body.sources, links: body.links, tools: body.tools, unverified: body.unverified };
        } else {
          const ctx: Ctx = { age, pm, get: <T,>(k: DataKey) => loadJson<T>(DATA[k]) };
          const local = await answer(t, ctx);
          r = { text: local.text, via: "offline", note: `The server refused (${body.detail ?? res.status}); answered offline.`,
                sources: local.sources, links: local.link ? [local.link] : [] };
        }
      }
    } catch (e) {
      const ctx: Ctx = { age, pm, get: <T,>(k: DataKey) => loadJson<T>(DATA[k]) };
      const local = await answer(t, ctx).catch(() => ({ text: `Could not reach backend: ${(e as Error).message}` }));
      r = { text: local.text, via: "offline", note: "Server unreachable; answered with offline fallback." };
    }
    setMsgs((m) => m.map((x, i) => (i === m.length - 1 ? { ...x, r, ms: performance.now() - t0 } : x)));
  };

  return (
    <div className={`ch ${compact ? "compact" : ""}`}>
      <div className="ch-mode">
        {status.enabled ? (
          <div className="ui-seg">
            {status.gemini && <button className={mode === "gemini" ? "on" : ""} onClick={() => setMode("gemini")}>Gemini</button>}
            {status.ollama && <button className={mode === "ollama" ? "on" : ""} onClick={() => setMode("ollama")}>Ollama (offline)</button>}
            <button className={mode === "rules" ? "on" : ""} onClick={() => setMode("rules")}>rules</button>
          </div>
        ) : <span className="db-muted">offline copilot{HAS_API ? " · set GEMINI_API_KEY or start Ollama for local LLM" : ""}</span>}
        {mode === "gemini" && <em>{status.gemini_model ?? status.model} · cloud AI</em>}
        {mode === "ollama" && <em>{status.ollama_model} · local offline LLM</em>}
        {mode === "rules" && <em>grounded rules & BM25 search</em>}
      </div>
      <div className="cp-log">
        {msgs.length === 0 && (
          <div className="cp-empty">
            <b>Ask about {GUIDE[page] ? `“${GUIDE[page].title}”` : "the cell"}.</b>
            <span>{mode === "gemini" ? "Gemini explains, grounded in the twin's live telemetry and documents." : mode === "ollama" ? "Local Qwen model answers offline, grounded in the twin's telemetry." : "Answers come from the twin's rule-based tools or documents, with the source."}</span>
            <div className="cp-ex row">{(compact ? ["What does this page show?", ...EXAMPLES.slice(0, 3)] : EXAMPLES).map((e) => <button key={e} onClick={() => ask(e)}>{e}</button>)}</div>
          </div>
        )}
        {msgs.map((m, i) => (
          <div key={i} className="cp-turn">
            <div className="cp-q">{m.q}</div>
            {m.r ? (
              <div className="cp-a">
                {m.r.via !== "offline" ? <div className="ch-md"><Md text={m.r.text} /></div> : <p>{m.r.text}</p>}
                {m.r.note && <p className={`ch-note ${m.r.unverified?.length ? "bad" : ""}`}>{m.r.unverified?.length ? "⚠ " : ""}{m.r.note}</p>}
                <div className="cp-src">
                  {m.r.text && <Speak text={m.r.text} />}
                  {m.r.links?.map((l) => <button key={l.page} className="db-link" onClick={() => go(l.page)}>open {l.label} →</button>)}
                  {m.r.sources && m.r.sources.length > 0 && <span title={m.r.sources.join("\n")}>grounded in: {m.r.sources[0]}{m.r.sources.length > 1 ? ` +${m.r.sources.length - 1}` : ""}</span>}
                  <em>{m.r.model ?? (m.r.via === "offline" ? "offline fallback" : m.r.via)}{m.r.tools?.length ? ` · ${[...new Set(m.r.tools)].join(", ")}` : ""}{m.ms !== undefined ? ` · ${(m.ms / 1000).toFixed(1)} s` : ""}</em>
                </div>
              </div>
            ) : <div className="cp-a"><p className="db-muted">{mode === "gemini" ? "asking Gemini…" : mode === "ollama" ? "asking local Ollama…" : "…"}</p></div>}
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
