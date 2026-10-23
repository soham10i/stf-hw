// The copilot: one conversation, two ways in - typed questions (the server picks the first
// ready model; a model at its limit hands over without a wait) or the voice.
// Sessions live on the server (sessions.py / store.py) and are listed as history; each keeps a
// context store - the facts the twin's tools established - that whichever model answers next is
// given, so a model at its limit hands over without the conversation losing anything. The full
// page shows history | conversation | context; the Ask panel on every page shows the same
// session, compactly. Without the API (the static demo) the browser's own copilot answers.
import { useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion, MotionConfig, type Variants } from "motion/react";
import { loadJson } from "../shared/data";
import { HAS_API } from "../shared/mode";
import { DATA, EXAMPLES, answer as offline, type Ctx, type DataKey } from "../copilot/copilot";
import { GUIDE } from "./guide";
import * as api from "./copilot/api";
import { Md, Message, openSource } from "./copilot/Message";
import { Voice } from "./copilot/Voice";
import { AnswerSettings, SettingsChip } from "./copilot/Settings";
import { CopilotMark, Icon } from "../shared/icons";

const TABS: [api.Tab, string, string][] = [
  ["chat", "Chat", "the models answer - whichever is free first"],
  ["voice", "Voice", "speak a question, hear the answer"],
];
// the model control: which engine answers is a server detail (the server walks its chain and
// answers with the first ready one, so a model at its limit costs one question, never a wait).
// The UI offers only "the server decides" and "this machine".
const MODELS: [api.Model, string, string][] = [
  ["auto", "Auto", "the first ready model answers - one at its limit never makes you wait"],
  ["local", "Local", "a model on this machine"],
];
const THINKING: Record<api.Tab, string> = { chat: "Asking the models…", voice: "Thinking…" };
// where answers come from: the server decides (Auto, orchestrate.py), or the operator does
const CHOICES: [api.Choice, string, string, string][] = [
  ["auto", "spark", "Auto", "The server picks: the twin's data, its documents, or the web when they cannot answer - and says why"],
  ["docs", "book", "Docs", "Only the twin's documents and tools: never the web"],
  ["web", "globe", "Web", "Search the web; every claim linked to its page, each page graded trusted or unvetted"],
  ["deep", "layers", "Deep", "Research: split into sub-questions, each searched, then written up together (slower, several searches)"],
];
// what to ask first, by who is asking (the twin's own questions stay first for the operator)
const PROFILE_EXAMPLES: Record<api.Audience, string[]> = {
  operator: [],
  engineer: ["What PFHd does PL d require for the E-stop?", "Derive the belt's stopping distance", "Compare EtherCAT and Modbus TCP for the remote I/O"],
  researcher: ["Deep research: virtual commissioning with FMI and OPC UA - state of the art",
    "Deep research: physics engines for industrial digital twins - accuracy vs real time",
    "What does the literature say about predictive maintenance of DC gear motors?"],
};
const HERO: Record<api.Audience, string> = {
  operator: "Short answers from the twin's own tools and documents, with their sources. Numbers are checked before you see them.",
  engineer: "Answers from the twin's tools and documents, the standards and datasheets behind them, and the web when they cannot answer.",
  researcher: "Researched reports from standards and peer-reviewed papers only - forums and social media are never used, and the evidence is rated.",
};
const EMPTY: api.Session["context"] = { facts: [], tools: [], models: [], page: null };
// one shared spring for the sliding highlights (the provider tabs, where-answers-come-from)
const PILL = { type: "spring", stiffness: 500, damping: 40 } as const;
// a popover's entrance and exit (history, context)
const POP = { initial: { opacity: 0, y: -6, scale: 0.985 }, animate: { opacity: 1, y: 0, scale: 1 },
  exit: { opacity: 0, y: -4, scale: 0.99 }, transition: { duration: 0.16, ease: "easeOut" } } as const;
// the empty state's example chips, rising one after another
const EX: Variants = { on: { transition: { staggerChildren: 0.05, delayChildren: 0.15 } } };
const EXI: Variants = { off: { opacity: 0, y: 8 }, on: { opacity: 1, y: 0, transition: { duration: 0.3, ease: "easeOut" } } };

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
  const [model, setModel] = useState<api.Model>(api.savedModel.get());
  const [status, setStatus] = useState<api.Status>({ enabled: false, model: null });
  const [sid, setSid] = useState<string | null>(api.currentSession.get());
  const [title, setTitle] = useState("");
  const [turns, setTurns] = useState<api.Turn[]>([]);
  const [context, setContext] = useState(EMPTY);
  const [memory, setMemory] = useState("");
  const [list, setList] = useState<api.Summary[]>([]);
  const [showList, setShowList] = useState(false);
  const [showCtx, setShowCtx] = useState(false);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [choice, setChoice] = useState<api.Choice>(api.savedChoice.get());
  const [prefs, setPrefs] = useState<api.Prefs>(api.savedPrefs.get());
  const [showSet, setShowSet] = useState(false);
  // the answer to read aloud by itself (a Voice question's): by its time, so it is spoken once,
  // not again when the list re-renders or the conversation is reopened
  const [speakNext, setSpeakNext] = useState<number | null>(null);
  const end = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);

  const refreshList = () => api.sessions().then(setList);
  const open = async (id: string | null) => {
    setSid(id); api.currentSession.set(id); setShowList(false); setSpeakNext(null);
    if (!id) { setTurns([]); setContext(EMPTY); setMemory(""); setTitle(""); return; }
    const s = await api.session(id);
    if (!s) { setSid(null); api.currentSession.set(null); setTurns([]); setContext(EMPTY); return; }
    setTurns(s.turns); setContext(s.context); setMemory(s.memory ?? ""); setTitle(s.title);
  };
  useEffect(() => { api.status().then(setStatus); open(sid); refreshList(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { end.current?.scrollIntoView({ block: "end", behavior: "smooth" }); }, [turns]);
  useEffect(() => { api.savedTab.set(tab); }, [tab]);
  useEffect(() => { api.savedModel.set(model); }, [model]);
  useEffect(() => { api.savedChoice.set(choice); }, [choice]);
  useEffect(() => { api.savedPrefs.set(prefs); }, [prefs]);
  // the tokens this conversation's answers used, whoever answered them
  const spent = useMemo(() => turns.reduce((n, t) => n + (t.usage?.tokens ?? 0), 0), [turns]);

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
        // the route, each step and the model's thinking arrive while it works: shown in the
        // pending answer, then folded above the answer itself
        const live = (p: api.Progress) => setTurns((m) => {
          const last = m[m.length - 1];
          if (!last?.pending) return m;
          const next = { ...last };
          if (p.route) next.route = p.route;
          if (p.step) next.steps = [...(next.steps ?? []), p.step];
          if (p.thinking) next.thinking = next.thinking ? `${next.thinking}\n\n${p.thinking}` : p.thinking;
          return [...m.slice(0, -1), next];
        });
        const r = await api.askStream({ question: t, page, provider: api.providerOf(model), session_id: sid, age, pm, mode: choice,
          depth: prefs.depth, audience: prefs.audience, sources: prefs.sources }, live);
        reply = { role: "assistant", text: r.answer, t: now, model: r.model, style: r.style, sources: r.sources, links: r.links,
          tools: r.tools, note: r.note, unverified: r.unverified, switched: r.switched, facts: r.facts, cites: r.cites,
          route: r.route, steps: r.steps, thinking: r.thinking, usage: r.usage, trace: r.trace };
        if (r.session) {
          setSid(r.session.id); api.currentSession.set(r.session.id); setTitle(r.session.title);
          api.session(r.session.id).then((s) => { if (s) { setContext(s.context); setMemory(s.memory ?? ""); } });
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

  const examples = useMemo(() => {
    if (compact) return ["What does this page show?", ...EXAMPLES.slice(0, 3)];
    const own = PROFILE_EXAMPLES[prefs.audience];
    return [...own, ...EXAMPLES].slice(0, 6);
  }, [compact, prefs.audience]);
  const pageTitle = GUIDE[page]?.title;
  const MODEL_AVAIL: Partial<Record<api.Model, boolean | undefined>> = { auto: true, local: status.ollama };

  const history = (
    <div className="cx-history">
      <button className="cx-new" onClick={() => open(null)}>＋ New chat</button>
      {list.length === 0 && <p className="cx-muted">No conversations yet.</p>}
      {list.map((s) => (
        <div key={s.id} className={`cx-hist ${s.id === sid ? "on" : ""}`}>
          <button onClick={() => open(s.id)} title={s.title}>
            <b>{s.title || "New chat"}</b><span>{api.ago(s.updated)} · {Math.floor((s.n_turns ?? 0) / 2)} questions</span>
          </button>
          <button className="cx-del" aria-label="Delete this conversation" title="Delete"
            onClick={async () => { await api.forget(s.id); if (s.id === sid) open(null); refreshList(); }}>×</button>
        </div>
      ))}
    </div>
  );

  // the documents this conversation's answers were built from, each once, in the order cited
  const docs = useMemo(() => {
    const seen = new Map<string, api.Cite>();
    for (const t of turns) for (const c of t.cites ?? []) if (c.kind !== "tool" && !seen.has(c.label)) seen.set(c.label, c);
    return [...seen.values()];
  }, [turns]);
  const answers = turns.filter((t) => t.role === "assistant" && !t.pending).length;
  const contextPanel = (
    <aside className="cx-context">
      <h3>Context</h3>
      <p className="cx-muted">What this conversation has established. Whichever model answers next is given all of it.</p>
      <div className="cx-ctx-stats">
        <div><b>{context.facts.length}</b><span>facts</span></div>
        <div><b>{docs.length}</b><span>documents</span></div>
        <div><b>{answers}</b><span>answers</span></div>
        <div><b>{api.kTokens(spent)}</b><span>tokens</span></div>
      </div>
      {/* each block folds away; the counts say what is inside before it is opened */}
      <details className="cx-sec" open={docs.length > 0}>
        <summary><Icon name="book" size={14} />Documents cited <span className="cx-sec-n">{docs.length}</span></summary>
        {docs.length ? (
          <ul className="cx-ctx-docs">
            {docs.map((c) => (
              <li key={c.label}>
                <button onClick={() => openSource(c)} title={c.quote ?? c.label}>
                  <b>{c.label.split(" > ").slice(-2).join(" › ")}</b>
                  <em>{c.kind === "web" ? c.label : `${c.file}:${c.line}`}</em>
                </button>
              </li>
            ))}
          </ul>
        ) : <em className="cx-muted">The passages answers quote are listed here; each opens at its line.</em>}
      </details>
      <details className="cx-sec" open={context.facts.length > 0}>
        <summary><Icon name="checklist" size={14} />Facts established <span className="cx-sec-n">{context.facts.length}</span></summary>
        {context.facts.length ? <CtxFacts facts={context.facts} />
          : <em className="cx-muted">The figures the twin's tools return are kept here, with where they came from.</em>}
      </details>
      <details className="cx-sec" open={context.models.length + context.tools.length > 0}>
        <summary><Icon name="cpu" size={14} />Models and tools <span className="cx-sec-n">{context.models.length + context.tools.length}</span></summary>
        <div className="cx-chips">
          {context.models.map((m) => <i key={m}>{m}</i>)}
          {context.tools.map((m) => <i key={m} className="tool">{m.replace(/_/g, " ")}</i>)}
          {!context.models.length && !context.tools.length && <em>none yet</em>}
        </div>
      </details>
      <details className="cx-sec" open>
        <summary><Icon name="overview" size={14} />This page</summary>
        <dl className="cx-ctx-kv">
          <div><dt>page</dt><dd>{pageTitle ?? page}</dd></div>
          {!compact && <div><dt>machine age</dt><dd>{age} shifts</dd></div>}
          <div><dt>preventive maintenance</dt><dd>{pm ? "on" : "off"}</dd></div>
        </dl>
      </details>
      {memory && (
        <details className="cx-sec cx-ctx-memory">
          <summary><Icon name="copilot" size={14} />What the next model is given</summary>
          <p className="cx-muted">This session's facts, as Markdown - added to the context of the next question, whichever model answers it.</p>
          <div className="cx-md"><Md text={memory} /></div>
        </details>
      )}
    </aside>
  );

  const body = (
    <MotionConfig reducedMotion="user">
    <section className={`cx-main ${compact ? "compact" : ""}`}>
      <header className="cx-head">
        <div className="cx-tabs" role="tablist">
          {TABS.map(([id, label, tip]) => (
            <button key={id} role="tab" aria-selected={tab === id} className={tab === id ? "on" : ""} onClick={() => setTab(id)} title={tip}>
              {tab === id && <motion.span layoutId="cx-tab-pill" className="cx-pill" transition={PILL} />}
              {label}
            </button>
          ))}
        </div>
        {HAS_API && !compact && tab === "chat" && (
          <select className="ui-select cx-model" value={model} onChange={(e) => setModel(e.target.value as api.Model)}
            aria-label="Model" title="Which model answers: Auto walks the chain in order, so a model at its limit never makes you wait">
            {MODELS.map(([id, label, tip]) => (
              <option key={id} value={id} disabled={MODEL_AVAIL[id] === false} title={tip}>
                {id === "auto" ? "Auto · first ready model" : `${label}${MODEL_AVAIL[id] === false ? " (not running)" : ""}`}
              </option>
            ))}
          </select>
        )}
        {HAS_API && (
          <button className={`cx-icon ${compact ? "" : "cx-hist-btn"}`} onClick={() => { setShowList(!showList); refreshList(); }} title="History" aria-label="History">☰</button>
        )}
        {compact && turns.length > 0 && <button className="cx-icon" onClick={() => open(null)} title="New chat" aria-label="New chat">＋</button>}
        {HAS_API && (
          <button className={`cx-icon ${showSet ? "on" : ""}`} onClick={() => { setShowSet(!showSet); setShowList(false); setShowCtx(false); api.status().then(setStatus); }}
            title="Answer settings: who is asking, depth, sources, cost" aria-label="Answer settings" aria-expanded={showSet}>
            <Icon name="cog" size={15} />
          </button>
        )}
        {!compact && (
          <button className={`cx-icon cx-ctx-btn ${showCtx ? "on" : ""}`} onClick={() => setShowCtx(!showCtx)} title="Context" aria-label="Show the context">
            ◎ <span>{context.facts.length}</span>
          </button>
        )}
      </header>
      <AnimatePresence>
        {!compact && showCtx && <motion.div className="cx-pop right" {...POP}><div className="cx-pop-in">{contextPanel}</div></motion.div>}
        {showList && <motion.div className={`cx-pop ${compact ? "" : "cx-pop-hist"}`} {...POP}><div className="cx-pop-in">{history}</div></motion.div>}
        {showSet && (
          <motion.div className="cx-pop right cx-pop-set" {...POP}>
            <div className="cx-pop-in">
              <div className="cx-pop-head"><b>Answer settings</b><button className="cx-icon" onClick={() => setShowSet(false)} aria-label="Close"><Icon name="close" size={14} /></button></div>
              <AnswerSettings prefs={prefs} set={setPrefs} status={status} spent={spent} />
            </div>
          </motion.div>
        )}
      </AnimatePresence>
      <AnimatePresence>{!compact && title && <motion.div className="cx-title" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>{title}</motion.div>}</AnimatePresence>

      <div className="cx-log">
        {turns.length === 0 && (
          <motion.div className="cx-hero" initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.35, ease: "easeOut" }}>
            <motion.div className="cx-orb" animate={{ y: [0, -4, 0] }} transition={{ duration: 3.2, repeat: Infinity, ease: "easeInOut" }}><CopilotMark size={30} /></motion.div>
            <b>{tab === "voice" ? "Ask by voice" : `Ask about ${pageTitle && page !== "copilot" ? `“${pageTitle}”` : "the cell"}`}</b>
            <span>{HERO[prefs.audience]}</span>
            {tab !== "voice" && (
              <motion.div className="cx-examples" variants={EX} initial="off" animate="on">
                {examples.map((e) => <motion.button key={e} variants={EXI} onClick={() => ask(e)}>{e}</motion.button>)}
              </motion.div>
            )}
          </motion.div>
        )}
        <AnimatePresence initial={false}>
          {turns.map((m, i) => (
            <motion.div key={`${i}-${m.t}`} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -6 }} transition={{ duration: 0.22, ease: "easeOut" }}>
              <Message turn={m} go={go} autoSpeak={m.role === "assistant" && !m.pending && m.t === speakNext} />
            </motion.div>
          ))}
        </AnimatePresence>
        <div ref={end} />
      </div>

      {tab === "voice" && <Voice busy={busy} onAsk={(t) => ask(t, true)} />}
      {HAS_API && tab !== "voice" && (
        <div className="cx-controls">
          <div className="cx-choice" role="radiogroup" aria-label="Where answers come from">
            {CHOICES.map(([id, icon, label, tip]) => (
              <button key={id} role="radio" aria-checked={choice === id} className={choice === id ? "on" : ""} title={tip} onClick={() => setChoice(id)}>
                {choice === id && <motion.span layoutId="cx-choice-pill" className="cx-pill" transition={PILL} />}
                <Icon name={icon} size={13} /><span className="cx-choice-l">{label}</span>
              </button>
            ))}
          </div>
          <SettingsChip prefs={prefs} open={showSet} onOpen={() => { setShowSet(!showSet); setShowList(false); setShowCtx(false); api.status().then(setStatus); }} />
        </div>
      )}
      <form className="cx-composer" onSubmit={(e) => { e.preventDefault(); ask(q); }}>
        <textarea ref={input} value={q} rows={1} placeholder={tab === "voice" ? "…or type" : compact ? "Ask about this page…" : "Ask anything about the cell — Enter to send"}
          onChange={(e) => setQ(e.target.value)} aria-label="Question"
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(q); } }} />
        <motion.button type="submit" disabled={!q.trim() || busy} aria-label="Send" whileTap={{ scale: 0.9 }}>{busy ? <span className="cx-spin" /> : "↑"}</motion.button>
      </form>
    </section>
    </MotionConfig>
  );

  if (compact) return <div className="cx compact">{body}</div>;
  // one rail beside the conversation: the chats above (new chat first), the context below
  return (
    <div className="cx full">
      <div className="cx-rail">
        <aside className="cx-side">{history}</aside>
        {contextPanel}
      </div>
      {body}
    </div>
  );
}
