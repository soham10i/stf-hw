// One message of the conversation. The operator's question; or the copilot's answer, drawn by
// its STYLE (the server classifies the question - respond.py): a highlight card for a quick
// figure, a status grid for "what is happening now", a table for a comparison, a checklist for
// steps. Every message can be copied; an answer can be read aloud and shows any hand-over between
// models, its sources, and links to the pages with the detail. Which provider answered is a
// server detail: it stays in the session's context, never in the UI.
import { useEffect, useRef, useState } from "react";
import { speech, speechStream, type Cite as Source, type Mode, type Style, type Turn } from "./api";
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
        <li><b>Written by</b> {turn.model === "rules" ? "the twin's tools alone (no language model)" : "the copilot's language model"}{turn.switched?.length ? `, after ${turn.switched.length} hand-over${turn.switched.length > 1 ? "s" : ""}` : ""}</li>
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
    if (/^\s*<!--/.test(line)) {
      while (i < lines.length && !/-->/.test(lines[i])) i++;
      continue;
    }
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
    } else { flush(); if (line.trim() && !/^\*?(Sources:\s*`|Generated from the twin's exports)/i.test(line.trim())) out.push(<p key={out.length}>{inline(line, i)}</p>); }
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

/** A raw-PCM player: base64 16-bit chunks queued on an AudioContext, each starting where the
    last one ends; the lead-in is the jitter buffer. Chunks may arrive slower than real time,
    so a chunk that would start in the past is nudged to "now" (a small gap, never overlap). */
function pcmPlayer(rate: number) {
  const ctx = new AudioContext({ sampleRate: rate });
  void ctx.resume().catch(() => { /* autoplay policy: finish() stands down */ });
  let next = ctx.currentTime + 0.35;
  let any = false;
  let stopped = false;
  let onEnd: (() => void) | null = null;
  const watch = () => {
    if (stopped) return;
    if (ctx.currentTime >= next - 0.03) onEnd?.();
    else window.setTimeout(watch, 120);
  };
  return {
    push(b64: string) {
      if (stopped) return;
      const bin = atob(b64);
      const n = bin.length >> 1;
      const pcm = new Int16Array(n);
      for (let i = 0; i < n; i++) pcm[i] = (bin.charCodeAt(2 * i + 1) << 8) | bin.charCodeAt(2 * i);
      const f32 = new Float32Array(n);
      for (let i = 0; i < n; i++) f32[i] = pcm[i] / 32768;
      const buf = ctx.createBuffer(1, n, rate);
      buf.getChannelData(0).set(f32);
      const src = ctx.createBufferSource();
      src.buffer = buf;
      src.connect(ctx.destination);
      if (next < ctx.currentTime) next = ctx.currentTime + 0.04;
      src.start(next);
      next += buf.duration;
      any = true;
    },
    /** Resolves once the buffered audio has all played (or nothing can play). */
    finish(): Promise<void> {
      if (!any || ctx.state === "suspended") return Promise.resolve();
      return new Promise((res) => { onEnd = res; watch(); });
    },
    stop() { stopped = true; onEnd?.(); void ctx.close().catch(() => {}); },
  };
}

/** Read aloud: the server's voice pipeline (ElevenLabs / Gemini / the local voice), streamed so
    the first words play while the rest is still synthesised; the whole-file voice, then the
    browser, are the fallbacks. Every play has a generation; stopping (or unmounting) moves it
    on, so a speech request that returns afterwards is dropped instead of played - which is
    what let React's development double-mount, or a fast second click, speak an answer twice. */
export function Speak({ text, auto = false }: { text: string; auto?: boolean }) {
  const [state, setState] = useState<"idle" | "loading" | "playing">("idle");
  const [by, setBy] = useState("");
  const audio = useRef<HTMLAudioElement | null>(null);
  const player = useRef<ReturnType<typeof pcmPlayer> | null>(null);
  const gen = useRef(0);
  const stop = () => {
    gen.current++;
    audio.current?.pause();
    audio.current = null;
    player.current?.stop();
    player.current = null;
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
    // the content only: no code, links, URLs or citations - and nothing after a
    // Sources/Resources heading (the evidence list is not read aloud; tts.py does the
    // same). Math is kept verbatim: tts.py's speakable() verbalizes the LaTeX, so the
    // markdown stripping below must not touch it - each expression is parked in a
    // placeholder and put back afterwards.
    const body = text.split(/^#{1,4}\s*(sources?|resources|references|further reading)\b.*$/im)[0];
    const math: string[] = [];
    const parked = body.replace(
      /\$\$[\s\S]+?\$\$|\\\[[\s\S]+?\\\]|\\\([\s\S]+?\\\)|\$[^$\n]{1,2000}\$/g,
      (m) => { math.push(m); return `${math.length - 1}`; },
    );
    const said = parked
      .replace(/```[\s\S]*?```/g, " (code) ")
      .replace(/!?\[([^\]]{1,160})\]\((https?:\/\/[^)\s]+)\)/g, "$1")
      .replace(/https?:\/\/\S+|www\.\S+/g, "")
      .replace(/\[[^\]]{1,140}\]|[*_`#>|]/g, "")
      .replace(/(\d+)/g, (_, i) => math[+i]);
    // the streamed voice: meta opens the player, chunks feed it as they arrive
    // (an array holder: closures assign it and TypeScript keeps the type)
    const file: { mime: string; by: string; parts: string[] }[] = [];
    try {
      const streamed = await speechStream(said, (ev) => {
        if (my !== gen.current) return;               // stopped meanwhile: drain quietly
        if (ev.type === "meta") {
          if (ev.meta.kind === "pcm") {
            // a long answer arrives sentence by sentence: a new meta means the provider or
            // sample rate changed mid-answer - cut the old player over so the two never overlap
            player.current?.stop();
            player.current = pcmPlayer(ev.meta.rate);
            setBy(ev.meta.by);
            setState("playing");
          } else file.push({ mime: ev.meta.mime, by: ev.meta.by, parts: [] });
        } else if (ev.type === "chunk") {
          if (player.current) player.current.push(ev.b64);
          else if (file.length) file[0].parts.push(ev.b64);
        }
      });
      if (my !== gen.current) return;                 // stopped meanwhile
      if (streamed) {
        if (player.current) {
          await player.current.finish();
          if (my === gen.current) { player.current = null; setState("idle"); }
          return;
        }
        if (file.length) {
          const bin = atob(file[0].parts.join(""));
          const bytes = new Uint8Array(bin.length);
          for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
          const url = URL.createObjectURL(new Blob([bytes], { type: file[0].mime }));
          const a = new Audio(url);
          audio.current = a;
          setBy(file[0].by);
          setState("playing");
          a.onended = () => { URL.revokeObjectURL(url); if (my === gen.current) { audio.current = null; setState("idle"); } };
          a.play().catch(() => { if (my === gen.current) stop(); });
          return;
        }
        return setState("idle");                      // an empty stream: nothing to say
      }
    } catch { /* fall through to the whole-file voice */ }
    const s = await speech(said);
    if (my !== gen.current) { if (s) URL.revokeObjectURL(s.url); return; }   // stopped meanwhile
    if (!s) {
      if (!window.speechSynthesis) return setState("idle");
      const u = new SpeechSynthesisUtterance(said.replace(/\s+/g, " ").trim());
      u.onend = () => { if (my === gen.current) setState("idle"); };
      setBy("browser voice"); setState("playing");
      window.speechSynthesis.cancel();
      window.speechSynthesis.speak(u);
      return;
    }
    const a = new Audio(s.url);
    audio.current = a;
    a.onended = () => { URL.revokeObjectURL(s.url); if (my === gen.current) { audio.current = null; setState("idle"); } };
    setBy(""); setState("playing");
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
  return <Answer turn={turn} go={go} autoSpeak={autoSpeak} />;
}

/** The finished answer. Its sources stay folded away behind a button in the footer - the answer
    reads clean, and the evidence is one tap open. */
function Answer({ turn, go, autoSpeak }: { turn: Turn; go: (p: string) => void; autoSpeak?: boolean }) {
  const [showSrc, setShowSrc] = useState(false);
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
          {turn.model === "rules" && <span className="cx-chip model rules">twin's tools</span>}
          {switched.length > 0 && (
            <span className="cx-chip switch" title={switched.map((s) => s.why).join("\n")}>
              ↷ handed over {switched.length > 1 ? `${switched.length}×` : ""}
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
        {showSrc && turn.cites && turn.cites.length > 0 && <Sources cites={turn.cites} text={turn.text} />}
        {turn.cites && <Trace turn={turn} />}
        <div className="cx-foot">
          {turn.cites && turn.cites.length > 0 && (
            <button className={`cx-link cx-src-btn ${showSrc ? "on" : ""}`} onClick={() => setShowSrc(!showSrc)} aria-expanded={showSrc}>
              <Icon name="book" size={13} />{showSrc ? "Hide sources" : `Sources (${turn.cites.length})`}
            </button>
          )}
          {turn.links?.map((l) => <button key={l.page} className="cx-link" onClick={() => go(l.page)}>{l.label} →</button>)}
          {!turn.cites && turn.sources && turn.sources.length > 0 && <span className="cx-src" title={turn.sources.join("\n")}>
            {turn.sources[0]}{turn.sources.length > 1 ? ` +${turn.sources.length - 1}` : ""}</span>}
          <span className="cx-actions"><CopyButton text={turn.text} label="Copy the answer" /><Speak text={turn.text} auto={autoSpeak} /></span>
        </div>
      </div>
    </div>
  );
}
