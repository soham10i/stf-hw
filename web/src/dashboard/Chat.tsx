// The copilot: one conversation, three ways in - Gemini, a local model (Ollama), or the voice.
// Sessions live on the server (sessions.py / store.py) and are listed as history; each keeps a
// context store - the facts the twin's tools established - that whichever model answers next is
// given, so a model at its limit hands over without the conversation losing anything. The full
// page shows history | conversation | context; the Ask panel on every page shows the same
// session, compactly. Without the API (the static demo) the browser's own copilot answers.
import { useEffect, useMemo, useRef, useState } from "react";
import { loadJson } from "../shared/data";
import { HAS_API } from "../shared/mode";
import { DATA, EXAMPLES, answer as offline, type Ctx, type DataKey } from "../copilot/copilot";
import { GUIDE } from "./guide";
import * as api from "./copilot/api";
import { Message } from "./copilot/Message";
import { Voice } from "./copilot/Voice";

const TABS: [api.Tab, string, string][] = [
  ["gemini", "Gemini", "cloud models, switching when one reaches its limit"],
  ["local", "Local", "a model on this machine (Ollama), Gemini when it is not running"],
  ["voice", "Voice", "speak a question, hear the answer"],
];
const PROVIDER: Record<api.Tab, string> = { gemini: "gemini", local: "ollama", voice: "auto" };
const THINKING: Record<api.Tab, string> = { gemini: "Asking Gemini…", local: "Asking the local model…", voice: "Thinking…" };
const EMPTY: api.Session["context"] = { facts: [], tools: [], models: [], page: null };

// The session's facts, grouped by where they came from (the tool's source), newest first:
// the panel shows the 12 most recent facts across groups and expands on demand.
function CtxFacts({ facts }: { facts: api.Session["context"]["facts"] }) {
  const [all, setAll] = useState(false);
  const groups = useMemo(() => {
    const m = new Map<string, typeof facts>();
    for (const f of [...facts].reverse()) {
      const g = (f[2] || "this session").split(/[>,(]/)[0].trim() || "this session";
      const arr = m.get(g) ?? [];
      arr.push(f);
      m.set(g, arr);
    }
    return [...m.entries()];
  }, [facts]);
  const flat = groups.flatMap(([, fs]) => fs);
  const blocks: { g: string; fs: typeof facts }[] = [];
  let budget = all ? flat.length : 12;
  for (const [g, fs] of groups) {
    if (budget <= 0) break;
    blocks.push({ g, fs: fs.slice(0, budget) });
    budget -= fs.length;
  }
  return (
    <div className="cx-fact-groups">
      {blocks.map(({ g, fs }) => (
        <div className="cx-fact-group" key={g}>
          <i>{g}</i>
          <ul className="cx-facts">
            {fs.map(([k, v, src]) => (
              <li key={k} title={src}><b>{k}</b><span>{v}</span></li>
            ))}
          </ul>
        </div>
      ))}
      {flat.length > 12 && (
        <button className="cx-more" onClick={() => setAll(!all)}>
          {all ? "Show less" : `Show all ${flat.length} facts`}
        </button>
      )}
    </div>
  );
}

export function Chat({ page, go, age = 140, pm = true, compact = false }: {
  page: string; go: (p: string) => void; age?: number; pm?: boolean; compact?: boolean;
}) {
  const [tab, setTab] = useState<api.Tab>(api.savedTab.get());
  const [status, setStatus] = useState<api.Status>({ enabled: false, model: null });
  const [sid, setSid] = useState<string | null>(api.currentSession.get());
  const [title, setTitle] = useState("");
  const [turns, setTurns] = useState<api.Turn[]>([]);
  const [context, setContext] = useState(EMPTY);
  const [list, setList] = useState<api.Summary[]>([]);
  const [showList, setShowList] = useState(false);
  const [showCtx, setShowCtx] = useState(false);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  // the answer to read aloud by itself (a Voice question's): by its time, so it is spoken once,
  // not again when the list re-renders or the conversation is reopened
  const [speakNext, setSpeakNext] = useState<number | null>(null);
  const end = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);

  const refreshList = () => api.sessions().then(setList);
  const open = async (id: string | null) => {
    setSid(id); api.currentSession.set(id); setShowList(false); setSpeakNext(null);
    if (!id) { setTurns([]); setContext(EMPTY); setTitle(""); return; }
    const s = await api.session(id);
    if (!s) { setSid(null); api.currentSession.set(null); setTurns([]); setContext(EMPTY); return; }
    setTurns(s.turns); setContext(s.context); setTitle(s.title);
  };
  useEffect(() => { api.status().then(setStatus); open(sid); refreshList(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { end.current?.scrollIntoView({ block: "end", behavior: "smooth" }); }, [turns]);
  useEffect(() => { api.savedTab.set(tab); }, [tab]);

  const ask = async (text: string, viaVoice = false) => {
    const t = text.trim();
    if (!t || busy) return;
    setQ(""); setBusy(true);
    const now = Date.now() / 1000;
    setTurns((m) => [...m, { role: "user", text: t, t: now }, { role: "assistant", text: THINKING[tab], t: now, pending: true }]);
    const t0 = performance.now();
    let reply: api.Turn;
    try {
      if (!HAS_API) {
        const ctx: Ctx = { age, pm, get: <T,>(k: DataKey) => loadJson<T>(DATA[k]) };
        const a = await offline(t, ctx);
        reply = { role: "assistant", text: a.text, t: now, model: "offline", sources: a.sources, links: a.link ? [a.link] : [], style: "answer" };
      } else {
        const r = await api.ask({ question: t, page, provider: PROVIDER[tab], session_id: sid, age, pm });
        reply = { role: "assistant", text: r.answer, t: now, model: r.model, style: r.style, sources: r.sources, links: r.links,
          tools: r.tools, note: r.note, unverified: r.unverified, switched: r.switched, facts: r.facts };
        if (r.session) {
          setSid(r.session.id); api.currentSession.set(r.session.id); setTitle(r.session.title);
          api.session(r.session.id).then((s) => s && setContext(s.context));
          refreshList();
        }
      }
    } catch (e) {
      reply = { role: "assistant", text: `I could not answer: ${(e as Error).message}`, t: now, model: "error", style: "answer" };
    }
    reply.ms = performance.now() - t0;
    reply.t = Date.now() / 1000;
    if (viaVoice) setSpeakNext(reply.t);
    setTurns((m) => [...m.slice(0, -1), reply]);
    setBusy(false);
    if (!viaVoice) input.current?.focus();
  };

  const avail: Record<api.Tab, boolean | undefined> = { gemini: status.gemini, local: status.ollama, voice: true };
  const examples = useMemo(() => (compact ? ["What does this page show?", ...EXAMPLES.slice(0, 3)] : EXAMPLES.slice(0, 6)), [compact]);
  const pageTitle = GUIDE[page]?.title;

  const history = (
    <div className="cx-history">
      <button className="cx-new" onClick={() => open(null)}>＋ New chat</button>
      {list.length === 0 && <p className="cx-muted">No conversations yet.</p>}
      {list.map((s) => (
        <div key={s.id} className={`cx-hist ${s.id === sid ? "on" : ""}`}>
          <button onClick={() => open(s.id)} title={s.title}>
            <b>{s.title || "New chat"}</b><span>{api.ago(s.updated)} · {Math.floor((s.n_turns ?? 0) / 2)} questions{s.last_model ? ` · ${s.last_model}` : ""}</span>
          </button>
          <button className="cx-del" aria-label="Delete this conversation" title="Delete"
            onClick={async () => { await api.forget(s.id); if (s.id === sid) open(null); refreshList(); }}>×</button>
        </div>
      ))}
    </div>
  );

  const contextPanel = (
    <aside className="cx-context">
      <h3>Context</h3>
      <p className="cx-muted">What this conversation has established. Whichever model answers next is given all of it.</p>
      <div className="cx-ctx-block">
        <span>Models that answered</span>
        <div className="cx-chips">{context.models.length ? context.models.map((m) => <i key={m}>{m}</i>) : <em>none yet</em>}</div>
      </div>
      <div className="cx-ctx-block">
        <span>Tools used</span>
        <div className="cx-chips">{context.tools.length ? context.tools.map((m) => <i key={m} className="tool">{m.replace(/_/g, " ")}</i>) : <em>none yet</em>}</div>
      </div>
      <div className="cx-ctx-block">
        <span>Known facts ({context.facts.length})</span>
        {context.facts.length ? (
          <CtxFacts facts={context.facts} />
        ) : <em className="cx-muted">Ask a question: the facts the tools return are kept here.</em>}
      </div>
      <div className="cx-ctx-block">
        <span>Page</span>
        <div className="cx-chips"><i>{pageTitle ?? page}</i>{!compact && <i>machine age {age} shifts</i>}<i>PM {pm ? "on" : "off"}</i></div>
      </div>
    </aside>
  );

  const body = (
    <section className={`cx-main ${compact ? "compact" : ""}`}>
      <header className="cx-head">
        <div className="cx-tabs" role="tablist">
          {TABS.map(([id, label, tip]) => (
            <button key={id} role="tab" aria-selected={tab === id} className={tab === id ? "on" : ""} onClick={() => setTab(id)} title={tip}>
              <i className={`dot ${avail[id] === false ? "off" : ""}`} />{label}
            </button>
          ))}
        </div>
        {compact && HAS_API && (
          <button className="cx-icon" onClick={() => { setShowList(!showList); refreshList(); }} title="History" aria-label="History">☰</button>
        )}
        {compact && turns.length > 0 && <button className="cx-icon" onClick={() => open(null)} title="New chat" aria-label="New chat">＋</button>}
        {!compact && (
          <button className={`cx-icon cx-ctx-btn ${showCtx ? "on" : ""}`} onClick={() => setShowCtx(!showCtx)} title="Context" aria-label="Show the context">
            ◎ <span>{context.facts.length}</span>
          </button>
        )}
      </header>
      {!compact && showCtx && <div className="cx-pop right">{contextPanel}</div>}
      {compact && showList && <div className="cx-pop">{history}</div>}
      {!compact && title && <div className="cx-title">{title}</div>}

      <div className="cx-log">
        {turns.length === 0 && (
          <div className="cx-hero">
            <div className="cx-orb">✦</div>
            <b>{tab === "voice" ? "Ask by voice" : `Ask about ${pageTitle ? `“${pageTitle}”` : "the cell"}`}</b>
            <span>Answers come from the twin's own tools and documents, with their sources. Numbers are checked before you see them.</span>
            {tab !== "voice" && <div className="cx-examples">{examples.map((e) => <button key={e} onClick={() => ask(e)}>{e}</button>)}</div>}
          </div>
        )}
        {turns.map((m, i) => <Message key={`${i}-${m.t}`} turn={m} go={go} autoSpeak={m.role === "assistant" && !m.pending && m.t === speakNext} />)}
        <div ref={end} />
      </div>

      {tab === "voice" && <Voice busy={busy} onAsk={(t) => ask(t, true)} />}
      <form className="cx-composer" onSubmit={(e) => { e.preventDefault(); ask(q); }}>
        <textarea ref={input} value={q} rows={1} placeholder={tab === "voice" ? "…or type" : compact ? "Ask about this page…" : "Ask anything about the cell — Enter to send"}
          onChange={(e) => setQ(e.target.value)} aria-label="Question"
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(q); } }} />
        <button type="submit" disabled={!q.trim() || busy} aria-label="Send">{busy ? <span className="cx-spin" /> : "↑"}</button>
      </form>
    </section>
  );

  if (compact) return <div className="cx compact">{body}</div>;
  return (
    <div className="cx full">
      <aside className="cx-side">{history}</aside>
      {body}
      {contextPanel}
    </div>
  );
}
