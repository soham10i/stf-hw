// One message of the conversation. The operator's question; or the copilot's answer, drawn by
// its STYLE (the server classifies the question - respond.py): a highlight card for a quick
// figure, a status grid for "what is happening now", a table for a comparison, a checklist for
// steps. Every message can be copied; an answer can be read aloud and shows which model wrote it,
// any hand-over between models, its sources, and links to the pages with the detail.
import { useEffect, useRef, useState } from "react";
import { speech, type Cite as Source, type Style, type Turn } from "./api";
import { CopilotMark, Icon } from "../../shared/icons";

const STYLE_LABEL: Record<Style, string> = {
  greeting: "hello", quick: "quick answer", compare: "comparison", steps: "steps", status: "live status",
  list: "list", explain: "explanation", answer: "answer",
};

const norm = (s: string) => s.toLowerCase().replace(/[›>]/g, ">").replace(/\s+/g, " ").trim();
/** The source an inline [citation] names: the same label, or one that starts with it. */
function findSource(src: string, cites: Source[] = []) {
  const n = norm(src);
  const i = cites.findIndex((c) => { const l = norm(c.label); return l === n || l.startsWith(n) || n.startsWith(l); });
  return i < 0 ? null : { i, c: cites[i] };
}
/** Open a document passage in the Docs page (the dashboard listens). */
export function openSource(c: Source) {
  if (c.kind === "doc" && c.file) window.dispatchEvent(new CustomEvent("stf:open-doc", { detail: { file: c.file, anchor: c.anchor, line: c.line } }));
  else if (c.kind === "web") window.open(c.label, "_blank", "noopener,noreferrer");
}

/** A citation: a numbered link to its source when the answer has it, else a small chip. */
function Cite({ src, cites }: { src: string; cites?: Source[] }) {
  const hit = findSource(src, cites);
  const short = src.split(/[>,(]/)[0].trim().replace(/ model$/, "");
  if (hit && (hit.c.kind === "doc" || hit.c.kind === "web"))
    return <button className="cx-cite n" title={`${hit.c.label}${hit.c.file ? `\n${hit.c.file}:${hit.c.line}` : ""}`} onClick={() => openSource(hit.c)}>{hit.i + 1}</button>;
  return <span className="cx-cite" title={src}>{hit ? `${hit.i + 1} ` : ""}{short.length > 28 ? short.slice(0, 26) + "…" : short}</span>;
}

/** The answer's sources, numbered as the text cites them; a document opens at the cited line. */
function Sources({ cites }: { cites: Source[] }) {
  return (
    <ol className="cx-sources">
      {cites.map((c, i) => (
        <li key={i} className={c.kind}>
          <span className="cx-src-n">{i + 1}</span>
          {c.kind === "doc" ? (
            <button onClick={() => openSource(c)} title={c.quote}>
              <b>{c.label.split(" > ").slice(-2).join(" › ")}</b>
              <em>{c.file}:{c.line}{c.score !== undefined ? ` · match ${c.score.toFixed(1)}` : ""}</em>
            </button>
          ) : c.kind === "web" ? (
            <a href={c.label} target="_blank" rel="noopener noreferrer"><b>{new URL(c.label).hostname}</b><em>{c.label}</em></a>
          ) : (
            <span><b>{c.label}</b><em>computed by the twin's tool {c.tool.replace(/_/g, " ")}</em></span>
          )}
        </li>
      ))}
    </ol>
  );
}

/** How the answer was made: what was retrieved and how well it matched, which tools computed
    facts, which model wrote it, and whether every number was found in the evidence. */
function Trace({ turn }: { turn: Turn }) {
  const docs = (turn.cites ?? []).filter((c) => c.kind === "doc");
  const tools = (turn.tools ?? []).filter((t) => t !== "search_docs");
  return (
    <details className="cx-trace">
      <summary>How this answer was made</summary>
      <ol>
        <li><b>Retrieved</b> {docs.length ? `${docs.length} passage${docs.length === 1 ? "" : "s"} from the documents (BM25 ranking; best match ${Math.max(...docs.map((d) => d.score ?? 0)).toFixed(1)})` : "no document passage"}</li>
        <li><b>Computed</b> {tools.length ? tools.map((t) => t.replace(/_/g, " ")).join(", ") : "no tool"}</li>
        <li><b>Written by</b> {turn.model === "rules" ? "the twin's tools alone (no language model)" : turn.model ?? "?"}{turn.switched?.length ? `, after ${turn.switched.length} hand-over${turn.switched.length > 1 ? "s" : ""}` : ""}</li>
        <li><b>Checked</b> {turn.unverified?.length ? `${turn.unverified.length} figure${turn.unverified.length > 1 ? "s" : ""} not found in the evidence: ${turn.unverified.join(", ")}` : "every number found in the evidence it was given"}</li>
      </ol>
    </details>
  );
}

/** Markdown for model answers: paragraphs, headings, lists (numbered too), tables, **bold**, [citations]. */
export function Md({ text, cites }: { text: string; cites?: Source[] }) {
  const inline = (s: string, k = 0) => s.split(/(\*\*[^*]+\*\*|\[[^\]]{1,140}\])/g).map((p, i) =>
    p.startsWith("**") ? <b key={`${k}-${i}`}>{p.slice(2, -2)}</b>
      : p.startsWith("[") && p.endsWith("]") ? <Cite key={`${k}-${i}`} src={p.slice(1, -1)} cites={cites} /> : p);
  const out: JSX.Element[] = [];
  const lines = text.split("\n");
  let list: { ordered: boolean; items: string[] } | null = null;
  const flush = () => {
    if (!list) return;
    const L = list.ordered ? "ol" : "ul";
    out.push(<L key={out.length}>{list.items.map((l, i) => <li key={i}>{inline(l, i)}</li>)}</L>);
    list = null;
  };
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (/^\s*\|.*\|\s*$/.test(line)) {                       // a table: header, separator, rows
      flush();
      const rows: string[][] = [];
      for (; i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i]); i++) {
        if (/^\s*\|?\s*:?-{2,}/.test(lines[i])) continue;
        rows.push(lines[i].trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim()));
      }
      i--;
      if (rows.length) {
        out.push(
          <div key={out.length} className="cx-table"><table>
            <thead><tr>{rows[0].map((c, j) => <th key={j}>{inline(c)}</th>)}</tr></thead>
            <tbody>{rows.slice(1).map((r, k) => <tr key={k}>{r.map((c, j) => <td key={j}>{inline(c, j)}</td>)}</tr>)}</tbody>
          </table></div>,
        );
      }
      continue;
    }
    const h = /^\s*#{1,4}\s+(.*)$/.exec(line);
    const ul = /^\s*[-*•]\s+(.*)$/.exec(line);
    const ol = /^\s*\d{1,2}[.)]\s+(.*)$/.exec(line);
    if (h) { flush(); out.push(<h4 key={out.length}>{inline(h[1])}</h4>); }
    else if (ul || ol) {
      const ordered = !!ol;
      if (list && list.ordered !== ordered) flush();
      list ??= { ordered, items: [] };
      list.items.push((ul ?? ol)![1]);
    } else { flush(); if (line.trim()) out.push(<p key={out.length}>{inline(line)}</p>); }
  }
  flush();
  return <>{out}</>;
}

export function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  const [done, setDone] = useState(false);
  return (
    <button className={`cx-icon ${done ? "ok" : ""}`} title={done ? "Copied" : label} aria-label={label}
      onClick={() => {
        navigator.clipboard?.writeText(text).then(() => { setDone(true); window.setTimeout(() => setDone(false), 1400); }).catch(() => undefined);
      }}>
      <Icon name={done ? "copied" : "copy"} size={15} />
    </button>
  );
}

/** The one voice speaking now, app-wide: starting another stops it, so answers never overlap. */
let speaking: (() => void) | null = null;

/** Read aloud: the server's voice pipeline (ElevenLabs / Gemini / the local voice), else the browser.
    Every play has a generation; stopping (or unmounting) moves it on, so a speech request that
    returns afterwards is dropped instead of played - which is what let React's development
    double-mount, or a fast second click, speak an answer twice. */
export function Speak({ text, auto = false }: { text: string; auto?: boolean }) {
  const [state, setState] = useState<"idle" | "loading" | "playing">("idle");
  const [by, setBy] = useState("");
  const audio = useRef<HTMLAudioElement | null>(null);
  const gen = useRef(0);
  const stop = () => {
    gen.current++;
    audio.current?.pause();
    audio.current = null;
    window.speechSynthesis?.cancel();
    if (speaking === stop) speaking = null;
    setState("idle");
  };
  const play = async () => {
    if (state !== "idle" || audio.current) return stop();
    speaking?.();                                   // one voice at a time
    speaking = stop;
    const my = ++gen.current;
    setState("loading");
    const s = await speech(text);
    if (my !== gen.current) { if (s) URL.revokeObjectURL(s.url); return; }   // stopped meanwhile
    if (!s) {
      if (!window.speechSynthesis) return setState("idle");
      const u = new SpeechSynthesisUtterance(text.replace(/\[[^\]]{1,140}\]|[*_`#>|]/g, ""));
      u.onend = () => { if (my === gen.current) setState("idle"); };
      setBy("browser voice"); setState("playing");
      window.speechSynthesis.cancel();
      window.speechSynthesis.speak(u);
      return;
    }
    const a = new Audio(s.url);
    audio.current = a;
    a.onended = () => { URL.revokeObjectURL(s.url); if (my === gen.current) { audio.current = null; setState("idle"); } };
    setBy(s.by); setState("playing");
    a.play().catch(() => { if (my === gen.current) stop(); });
  };
  useEffect(() => {
    // a tick later, so React's development double-mount cancels the first attempt before any
    // speech is requested (one request, one voice)
    const t = auto ? window.setTimeout(play, 0) : 0;
    return () => { window.clearTimeout(t); stop(); };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <button className={`cx-icon speak ${state}`} onClick={play} title={state === "idle" ? "Read aloud" : `Stop${by ? ` (${by})` : ""}`}
      aria-label={state === "idle" ? "Read aloud" : "Stop reading"}>
      {state === "loading" ? <span className="cx-spin" /> : <Icon name={state === "playing" ? "stop" : "speaker"} size={15} />}
    </button>
  );
}

/** The figure a quick answer leads with: its first bold value. */
const leadFigure = (t: string) => /\*\*([^*]{1,40})\*\*/.exec(t)?.[1];

export function Message({ turn, go, autoSpeak = false }: { turn: Turn; go: (p: string) => void; autoSpeak?: boolean }) {
  if (turn.role === "user") {
    return (
      <div className="cx-row user">
        <div className="cx-bubble user">{turn.text}</div>
        <div className="cx-tools"><CopyButton text={turn.text} label="Copy the question" /></div>
      </div>
    );
  }
  if (turn.pending) {
    return (
      <div className="cx-row bot">
        <div className="cx-avatar"><CopilotMark size={18} /></div>
        <div className="cx-bubble bot pending"><span className="cx-dots"><i /><i /><i /></span><em>{turn.text}</em></div>
      </div>
    );
  }
  const style = turn.style ?? "answer";
  const fig = style === "quick" ? leadFigure(turn.text) : undefined;
  const switched = (turn.switched ?? []).filter((s) => s.to !== "next" || s.why);
  return (
    <div className="cx-row bot">
      <div className={`cx-avatar ${turn.model === "rules" ? "rules" : ""}`} title={turn.model === "rules" ? "Answered by the twin's tools alone" : "The copilot"}><CopilotMark size={18} /></div>
      <div className={`cx-bubble bot s-${style}`}>
        <div className="cx-meta">
          <span className="cx-chip style">{STYLE_LABEL[style]}</span>
          {turn.model && <span className={`cx-chip model ${turn.model === "rules" ? "rules" : ""}`}>{turn.model === "rules" ? "twin's tools" : turn.model}</span>}
          {switched.length > 0 && (
            <span className="cx-chip switch" title={switched.map((s) => `${s.from} → ${s.to ?? "next"}: ${s.why}`).join("\n")}>
              ↷ switched {switched.length > 1 ? `${switched.length}×` : ""}
            </span>
          )}
          {turn.ms !== undefined && <span className="cx-time">{(turn.ms / 1000).toFixed(1)} s</span>}
        </div>
        {fig && <div className="cx-figure">{fig}</div>}
        {style === "status" && turn.facts && turn.facts.length > 0 && !/\*\*[^*]+\*\*:/.test(turn.text) ? (
          <div className="cx-grid">{turn.facts.slice(0, 6).map(([k, v]) => <div key={k}><span>{k}</span><b>{v}</b></div>)}</div>
        ) : null}
        <div className="cx-md"><Md text={fig ? turn.text.replace(`**${fig}**`, fig) : turn.text} cites={turn.cites} /></div>
        {turn.note && <p className={`cx-note ${turn.unverified?.length ? "bad" : ""}`}>{turn.unverified?.length ? "⚠ " : "ⓘ "}{turn.note}</p>}
        {turn.cites && turn.cites.length > 0 && <Sources cites={turn.cites} />}
        {turn.cites && <Trace turn={turn} />}
        <div className="cx-foot">
          {turn.links?.map((l) => <button key={l.page} className="cx-link" onClick={() => go(l.page)}>{l.label} →</button>)}
          {!turn.cites && turn.sources && turn.sources.length > 0 && <span className="cx-src" title={turn.sources.join("\n")}>
            {turn.sources[0]}{turn.sources.length > 1 ? ` +${turn.sources.length - 1}` : ""}</span>}
          <span className="cx-actions"><CopyButton text={turn.text} label="Copy the answer" /><Speak text={turn.text} auto={autoSpeak} /></span>
        </div>
      </div>
    </div>
  );
}
