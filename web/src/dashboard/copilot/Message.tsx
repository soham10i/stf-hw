// One message of the conversation. The operator's question; or the copilot's answer, drawn by
// its STYLE (the server classifies the question - respond.py): a highlight card for a quick
// figure, a status grid for "what is happening now", a table for a comparison, a checklist for
// steps. Every message can be copied; an answer can be read aloud and shows which model wrote it,
// any hand-over between models, its sources, and links to the pages with the detail.
import { useEffect, useRef, useState } from "react";
import { speech, type Style, type Turn } from "./api";

const STYLE_LABEL: Record<Style, string> = {
  greeting: "hello", quick: "quick answer", compare: "comparison", steps: "steps", status: "live status",
  list: "list", explain: "explanation", answer: "answer",
};

/** A citation as a small chip: the source's short name, the whole of it on hover. */
function Cite({ src }: { src: string }) {
  const short = src.split(/[>,(]/)[0].trim().replace(/ model$/, "");
  return <span className="cx-cite" title={src}>{short.length > 28 ? short.slice(0, 26) + "…" : short}</span>;
}

/** Markdown for model answers: paragraphs, headings, lists (numbered too), tables, **bold**, [citations]. */
export function Md({ text }: { text: string }) {
  const inline = (s: string, k = 0) => s.split(/(\*\*[^*]+\*\*|\[[^\]]{1,140}\])/g).map((p, i) =>
    p.startsWith("**") ? <b key={`${k}-${i}`}>{p.slice(2, -2)}</b>
      : p.startsWith("[") && p.endsWith("]") ? <Cite key={`${k}-${i}`} src={p.slice(1, -1)} /> : p);
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
      {done ? "✓" : "⧉"}
    </button>
  );
}

/** Read aloud: the server's voice pipeline (ElevenLabs / Gemini / the local voice), else the browser. */
export function Speak({ text, auto = false }: { text: string; auto?: boolean }) {
  const [state, setState] = useState<"idle" | "loading" | "playing">("idle");
  const [by, setBy] = useState("");
  const audio = useRef<HTMLAudioElement | null>(null);
  const stop = () => { audio.current?.pause(); audio.current = null; window.speechSynthesis?.cancel(); setState("idle"); };
  const browser = () => {
    if (!window.speechSynthesis) return setState("idle");
    const u = new SpeechSynthesisUtterance(text.replace(/\[[^\]]{1,140}\]|[*_`#>|]/g, ""));
    u.onend = () => setState("idle");
    setBy("browser voice"); setState("playing");
    window.speechSynthesis.speak(u);
  };
  const play = async () => {
    if (state !== "idle") return stop();
    setState("loading");
    const s = await speech(text);
    if (!s) return browser();
    const a = new Audio(s.url);
    audio.current = a;
    a.onended = () => { URL.revokeObjectURL(s.url); setState("idle"); };
    setBy(s.by); setState("playing");
    a.play().catch(browser);
  };
  useEffect(() => { if (auto) play(); return stop; }, []); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <button className={`cx-icon speak ${state}`} onClick={play} title={state === "idle" ? "Read aloud" : `Stop${by ? ` (${by})` : ""}`}
      aria-label={state === "idle" ? "Read aloud" : "Stop reading"}>
      {state === "loading" ? <span className="cx-spin" /> : state === "playing" ? "■" : "🔊"}
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
        <div className="cx-avatar">✦</div>
        <div className="cx-bubble bot pending"><span className="cx-dots"><i /><i /><i /></span><em>{turn.text}</em></div>
      </div>
    );
  }
  const style = turn.style ?? "answer";
  const fig = style === "quick" ? leadFigure(turn.text) : undefined;
  const switched = (turn.switched ?? []).filter((s) => s.to !== "next" || s.why);
  return (
    <div className="cx-row bot">
      <div className={`cx-avatar ${turn.model === "rules" ? "rules" : ""}`}>✦</div>
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
        <div className="cx-md"><Md text={fig ? turn.text.replace(`**${fig}**`, fig) : turn.text} /></div>
        {turn.note && <p className={`cx-note ${turn.unverified?.length ? "bad" : ""}`}>{turn.unverified?.length ? "⚠ " : "ⓘ "}{turn.note}</p>}
        <div className="cx-foot">
          {turn.links?.map((l) => <button key={l.page} className="cx-link" onClick={() => go(l.page)}>{l.label} →</button>)}
          {turn.sources && turn.sources.length > 0 && <span className="cx-src" title={turn.sources.join("\n")}>
            {turn.sources[0]}{turn.sources.length > 1 ? ` +${turn.sources.length - 1}` : ""}</span>}
          <span className="cx-actions"><CopyButton text={turn.text} label="Copy the answer" /><Speak text={turn.text} auto={autoSpeak} /></span>
        </div>
      </div>
    </div>
  );
}
