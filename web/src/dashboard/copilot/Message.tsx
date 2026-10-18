// One message of the conversation. The operator's question; or the copilot's answer, drawn by
// its STYLE (the server classifies the question - respond.py): a highlight card for a quick
// figure, a status grid for "what is happening now", a table for a comparison, a checklist for
// steps. Every message can be copied; an answer can be read aloud and shows which model wrote it,
// any hand-over between models, its sources, and links to the pages with the detail.
import { useEffect, useRef, useState } from "react";
import { speech, type Cite as Source, type Mode, type Style, type Turn } from "./api";
import { CopilotMark, Icon } from "../../shared/icons";
import { TeX, displayBlock, mathSplit } from "../../shared/tex";

const STYLE_LABEL: Record<Style, string> = {
  greeting: "hello", quick: "quick answer", compare: "comparison", steps: "steps", status: "live status",
  list: "list", explain: "explanation", derive: "derivation", research: "research", answer: "answer",
};
/** Where the server sent the question (orchestrate.py): its icon and name. */
export const MODE: Record<Mode, [string, string]> = {
  chat: ["copilot", "conversation"], twin: ["cube", "twin data"], docs: ["book", "documents"],
  web: ["globe", "web search"], deep: ["layers", "deep research"],
};

const norm = (s: string) => s.toLowerCase().replace(/[›>]/g, ">").replace(/\s+/g, " ").trim();
/** The source an inline [citation] names: the same label, one that starts with it, the same
    document and section (the model may skip a heading level), or a file and line. */
function findSource(src: string, cites: Source[] = []) {
  const n = norm(src);
  let i = cites.findIndex((c) => { const l = norm(c.label); return l === n || l.startsWith(n) || n.startsWith(l); });
  if (i < 0) {
    const parts = n.split(" > ");
    i = cites.findIndex((c) => {
      const l = norm(c.label).split(" > ");
      return parts.length > 1 && l[0] === parts[0] && l[l.length - 1].startsWith(parts[parts.length - 1]);
    });
  }
  const at = /([\w./-]+\.md)(?:,?\s*(?:line\s*|:)(\d+))?/i.exec(src);
  if (i < 0 && at) {
    const line = Number(at[2] ?? 0);
    let best = -1;
    cites.forEach((c, k) => {
      if (c.file === at[1] && (c.line ?? 0) <= (line || Infinity) && (best < 0 || (c.line ?? 0) > (cites[best].line ?? 0))) best = k;
    });
    i = best;
  }
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

const hostOf = (u: string) => { try { return new URL(u).hostname.replace(/^www\./, ""); } catch { return u; } };

/** The answer's sources, numbered as the text cites them; a document opens at the cited line, a
    web page in a new tab, graded by its host (a standards body, publisher or manufacturer is
    "trusted", anything else "unvetted"). */
function Sources({ cites, text }: { cites: Source[]; text: string }) {
  // the sources the answer cites first; the rest of what the model was given folded below
  const used = new Set<number>();
  for (const m of text.matchAll(/\[([^\]]{1,200})\](?!\()/g)) { const hit = findSource(m[1], cites); if (hit) used.add(hit.i); }
  for (const m of text.matchAll(/\]\((https?:\/\/[^)\s]+)\)/g)) { const k = cites.findIndex((c) => c.label === m[1]); if (k >= 0) used.add(k); }
  const all = cites.map((c, i) => ({ c, i }));
  const shown = used.size ? all.filter(({ c, i }) => used.has(i) || c.kind === "tool") : all;
  const rest = used.size ? all.filter(({ c, i }) => !used.has(i) && c.kind !== "tool") : [];
  return (
    <>
      <SourceList items={shown} />
      {rest.length > 0 && (
        <details className="cx-more-src">
          <summary>{rest.length} more source{rest.length > 1 ? "s" : ""} the model was given</summary>
          <SourceList items={rest} />
        </details>
      )}
    </>
  );
}

function SourceList({ items }: { items: { c: Source; i: number }[] }) {
  return (
    <ol className="cx-sources">
      {items.map(({ c, i }) => (
        <li key={i} className={c.kind}>
          <span className="cx-src-n">{i + 1}</span>
          {c.kind === "doc" ? (
            <button onClick={() => openSource(c)} title={c.quote}>
              <b>{c.label.split(" > ").slice(-2).join(" › ")}</b>
              <em>{c.file}:{c.line}{c.score ? ` · match ${c.score.toFixed(1)}` : ""}</em>
            </button>
          ) : c.kind === "web" ? (
            <a href={c.label} target="_blank" rel="noopener noreferrer" title={c.label}>
              <b>{c.title && c.title !== c.label ? c.title : hostOf(c.label)}</b>
              <em><span className={`cx-trust ${c.trusted ? "ok" : ""}`}>{c.trusted ? "trusted" : "unvetted"}</span>{hostOf(c.label)}{c.cited ? " · cited" : ""}</em>
            </a>
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
  const web = (turn.cites ?? []).filter((c) => c.kind === "web");
  const tools = (turn.tools ?? []).filter((t) => !["search_docs", "web_search", "web_research"].includes(t));
  return (
    <details className="cx-trace">
      <summary>How this answer was made</summary>
      <ol>
        {turn.route && <li><b>Routed</b> to {MODE[turn.route.mode]?.[1] ?? turn.route.mode}: {turn.route.why.join("; ")}</li>}
        {web.length > 0 && <li><b>Searched</b> the web: {web.length} page{web.length > 1 ? "s" : ""}, {web.filter((c) => c.trusted).length} from trusted hosts</li>}
        <li><b>Retrieved</b> {docs.length ? `${docs.length} passage${docs.length === 1 ? "" : "s"} from the documents (BM25 ranking; best match ${Math.max(...docs.map((d) => d.score ?? 0)).toFixed(1)})` : "no document passage"}</li>
        <li><b>Computed</b> {tools.length ? tools.map((t) => t.replace(/_/g, " ")).join(", ") : "no tool"}</li>
        <li><b>Written by</b> {turn.model === "rules" ? "the twin's tools alone (no language model)" : turn.model ?? "?"}{turn.switched?.length ? `, after ${turn.switched.length} hand-over${turn.switched.length > 1 ? "s" : ""}` : ""}</li>
        <li><b>Checked</b> {turn.unverified?.length ? `${turn.unverified.length} figure${turn.unverified.length > 1 ? "s" : ""} not found in the evidence: ${turn.unverified.join(", ")}` : "every number found in the evidence it was given"}</li>
      </ol>
    </details>
  );
}

/** A fenced code block: its language, the code, and a copy button. */
function Code({ lang, code }: { lang: string; code: string }) {
  return (
    <div className="cx-code">
      <div className="cx-code-head"><span>{lang || "code"}</span><CopyButton text={code} label="Copy the code" /></div>
      <pre><code>{code}</code></pre>
    </div>
  );
}

/** Markdown for model answers: paragraphs, headings, lists (numbered too), tables, fenced code,
    LaTeX ($...$, $$...$$, \(...\), \[...\]), **bold**, *emphasis*, `code`, links, [citations]. */
export function Md({ text, cites }: { text: string; cites?: Source[] }) {
  const words = (s: string, k: string) => s.split(/(`[^`]+`|\*\*[^*]+\*\*|\[[^\]]{1,200}\]\(https?:\/\/[^)\s]+\)|\[[^\]]{1,200}\]|\*[^*\s][^*]*\*)/g).map((p, i) => {
    const key = `${k}-${i}`;
    if (p.startsWith("`") && p.endsWith("`") && p.length > 1) return <code key={key}>{p.slice(1, -1)}</code>;
    if (p.startsWith("**") && p.endsWith("**")) return <b key={key}>{p.slice(2, -2)}</b>;
    const link = /^\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)$/.exec(p);
    if (link) {
      const n = (cites ?? []).findIndex((c) => c.kind === "web" && c.label === link[2]);
      return <a key={key} className="cx-a" href={link[2]} target="_blank" rel="noopener noreferrer" title={link[2]}>{link[1]}{n >= 0 && <sup>{n + 1}</sup>}</a>;
    }
    if (p.startsWith("[") && p.endsWith("]")) return <Cite key={key} src={p.slice(1, -1)} cites={cites} />;
    if (p.startsWith("*") && p.endsWith("*") && p.length > 2) return <em key={key}>{p.slice(1, -1)}</em>;
    return p;
  });
  // in a table cell a displayed formula is drawn inline: a narrow column cannot hold a block
  const inline = (s: string, k: number | string = 0, flat = false) => mathSplit(s).map((g, i) =>
    g.kind === "text" ? <span key={`${k}.${i}`}>{words(g.s, `${k}.${i}`)}</span> : <TeX key={`${k}.${i}`} s={g.s} display={g.kind === "display" && !flat} />);
  const out: JSX.Element[] = [];
  const lines = text.split("\n");
  // a numbered list keeps its numbers when an equation or a paragraph splits it (start=)
  let list: { ordered: boolean; start: number; items: string[] } | null = null;
  const flush = () => {
    if (!list) return;
    const items = list.items.map((l, i) => <li key={i}>{inline(l, i)}</li>);
    out.push(list.ordered ? <ol key={out.length} start={list.start}>{items}</ol> : <ul key={out.length}>{items}</ul>);
    list = null;
  };
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const fence = /^\s*```\s*([\w+#.-]*)\s*$/.exec(line);
    if (fence) {                                              // a fenced code block
      flush();
      let j = i + 1;
      while (j < lines.length && !/^\s*```\s*$/.test(lines[j])) j++;
      out.push(<Code key={out.length} lang={fence[1]} code={lines.slice(i + 1, j).join("\n")} />);
      i = j;
      continue;
    }
    const tex = displayBlock(lines, i);
    if (tex) {                                                // a displayed formula over several lines
      flush();
      out.push(<div key={out.length} className="cx-tex"><TeX s={tex[0]} display /></div>);
      i = tex[1];
      continue;
    }
    if (/^\s*\|.*\|\s*$/.test(line)) {                       // a table: header, separator, rows
      flush();
      const rows: string[][] = [];
      for (; i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i]); i++) {
        if (/^\s*\|?\s*:?-{2,}/.test(lines[i])) continue;
        rows.push(lines[i].trim().replace(/^\||\|$/g, "").split(/(?<!\\)\|/).map((c) => c.trim()));
      }
      i--;
      if (rows.length) {
        out.push(
          <div key={out.length} className="cx-table"><table>
            <thead><tr>{rows[0].map((c, j) => <th key={j}>{inline(c, `h${j}`, true)}</th>)}</tr></thead>
            <tbody>{rows.slice(1).map((r, k) => <tr key={k}>{r.map((c, j) => <td key={j}>{inline(c, `${k}-${j}`, true)}</td>)}</tr>)}</tbody>
          </table></div>,
        );
      }
      continue;
    }
    const h = /^\s*#{1,4}\s+(.*)$/.exec(line);
    const ul = /^\s*[-*•]\s+(.*)$/.exec(line);
    const ol = /^\s*(\d{1,2})[.)]\s+(.*)$/.exec(line);
    if (h) { flush(); out.push(<h4 key={out.length}>{inline(h[1], i)}</h4>); }
    else if (/^\s*(-{3,}|\*{3,}|_{3,})\s*$/.test(line)) { flush(); out.push(<hr key={out.length} />); }
    else if (ul || ol) {
      const ordered = !!ol;
      if (list && list.ordered !== ordered) flush();
      list ??= { ordered, start: ol ? Number(ol[1]) : 1, items: [] };
      list.items.push(ol ? ol[2] : ul![1]);
    } else if (/^\s{2,}\S/.test(line) && list) {             // a list item's continuation line
      list.items[list.items.length - 1] += "\n" + line.trim();
    } else { flush(); if (line.trim()) out.push(<p key={out.length}>{inline(line, i)}</p>); }
  }
  flush();
  return <>{out}</>;
}

/** The model's work before it answered: the route and why, each step (retrieval, tools, models,
    searches) and its own reasoning. Open while it works; folded once the answer is there. */
function Thinking({ turn, live = false }: { turn: Turn; live?: boolean }) {
  const [t0] = useState(() => performance.now());
  const [, tick] = useState(0);
  useEffect(() => {
    if (!live) return;
    const id = window.setInterval(() => tick((n) => n + 1), 500);
    return () => window.clearInterval(id);
  }, [live]);
  const steps = turn.steps ?? [];
  if (!live && !steps.length && !turn.thinking && !turn.route) return null;
  const secs = live ? (performance.now() - t0) / 1000 : (turn.ms ?? 0) / 1000;
  const mode = turn.route ? MODE[turn.route.mode] : null;
  return (
    <details className={`cx-think ${live ? "live" : ""}`} open={live || undefined}>
      <summary>
        <Icon name="brain" size={14} />
        <span>{live ? `Thinking… ${secs.toFixed(0)} s` : secs ? `Thought for ${secs.toFixed(1)} s` : "Reasoning and steps"}</span>
        {mode && <span className="cx-think-mode"><Icon name={mode[0]} size={12} />{mode[1]}</span>}
      </summary>
      <div className="cx-think-body">
        {turn.route && <p className="cx-think-why"><b>Route.</b> {turn.route.why.join("; ")}.</p>}
        {steps.length > 0 && <ol className="cx-think-steps">{steps.map((s, i) => <li key={i}>{s}</li>)}</ol>}
        {/* the model's own notes, as written: raw text, not Markdown (its "*" is a multiplication) */}
        {turn.thinking && <div className="cx-think-text plain">{turn.thinking}</div>}
        {live && !turn.thinking && <p className="cx-muted">The model's reasoning appears here when it returns it.</p>}
      </div>
    </details>
  );
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
    const said = text.replace(/\$\$[\s\S]+?\$\$|\\\[[\s\S]+?\\\]/g, " (formula) ").replace(/```[\s\S]*?```/g, " (code) ");
    const s = await speech(said);
    if (my !== gen.current) { if (s) URL.revokeObjectURL(s.url); return; }   // stopped meanwhile
    if (!s) {
      if (!window.speechSynthesis) return setState("idle");
      const u = new SpeechSynthesisUtterance(said.replace(/\[[^\]]{1,140}\]|[*_`#>|]/g, ""));
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
        <div className="cx-bubble bot pending">
          <Thinking turn={turn} live />
          <div className="cx-pending"><span className="cx-dots"><i /><i /><i /></span><em>{turn.text}</em></div>
        </div>
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
          {turn.route && MODE[turn.route.mode] && (
            <span className={`cx-chip route m-${turn.route.mode}`} title={turn.route.why.join("\n")}>
              <Icon name={MODE[turn.route.mode][0]} size={12} />{MODE[turn.route.mode][1]}
            </span>
          )}
          {turn.model && <span className={`cx-chip model ${turn.model === "rules" ? "rules" : ""}`}>{turn.model === "rules" ? "twin's tools" : turn.model}</span>}
          {switched.length > 0 && (
            <span className="cx-chip switch" title={switched.map((s) => `${s.from} → ${s.to ?? "next"}: ${s.why}`).join("\n")}>
              ↷ switched {switched.length > 1 ? `${switched.length}×` : ""}
            </span>
          )}
          {turn.ms !== undefined && <span className="cx-time">{(turn.ms / 1000).toFixed(1)} s</span>}
        </div>
        <Thinking turn={turn} />
        {fig && <div className="cx-figure">{fig}</div>}
        {style === "status" && turn.facts && turn.facts.length > 0 && !/\*\*[^*]+\*\*:/.test(turn.text) ? (
          <div className="cx-grid">{turn.facts.slice(0, 6).map(([k, v]) => <div key={k}><span>{k}</span><b>{v}</b></div>)}</div>
        ) : null}
        <div className="cx-md"><Md text={fig ? turn.text.replace(`**${fig}**`, fig) : turn.text} cites={turn.cites} /></div>
        {turn.note && <p className={`cx-note ${turn.unverified?.length ? "bad" : ""}`}>{turn.unverified?.length ? "⚠ " : "ⓘ "}{turn.note}</p>}
        {turn.cites && turn.cites.length > 0 && <Sources cites={turn.cites} text={turn.text} />}
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
