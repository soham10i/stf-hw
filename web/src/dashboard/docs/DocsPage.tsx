// The Docs page: the project's documents as the copilot reads them (its knowledge base indexes
// the same files: web/scripts/copilot-kb.ts copies them to public/copilot/<path>). A document
// opens at a heading or at a cited line, highlighted - which is how an answer's source is
// checked. The PLC reference's figures are drawn from the export the program is generated from.
import { useEffect, useMemo, useRef, useState } from "react";
import { loadJson } from "../../shared/data";
import type { CadDoc } from "../../shared/model";
import { Markdown, slug } from "./Markdown";
import { Architecture, Network, Sfc, type Control } from "./PlcDiagrams";

const BASE = import.meta.env.BASE_URL;
const REPO = "https://github.com/soham10i/stf-hw/blob/main/";
export type DocTarget = { file: string; anchor?: string; line?: number };

/** Where a document belongs in the library. */
function group(f: string) {
  if (f.startsWith("docs/plc/")) return "PLC program";
  if (f.startsWith("docs/vision/")) return "Vision QC";
  if (f.startsWith("docs/assistant/machine")) return "The machine";
  if (f.startsWith("docs/assistant/panel") || f.startsWith("docs/assistant/twin")) return "The 3D twin";
  if (f.startsWith("docs/assistant/dashboard")) return "Dashboard pages";
  if (f.startsWith("docs/assistant/")) return "Operations";
  return "Project documents";
}
const ORDER = ["PLC program", "Vision QC", "The machine", "Operations", "The 3D twin", "Dashboard pages", "Project documents"];

function useText(file: string | undefined) {
  const [t, setT] = useState<{ file: string; text: string } | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    if (!file) return;
    let live = true;
    setErr(null);
    fetch(`${BASE}copilot/${file}`)
      .then((r) => (r.ok ? r.text() : Promise.reject(new Error(`${r.status}`))))
      .then((text) => { if (live) setT({ file, text }); })
      .catch((e) => { if (live) setErr(`This document could not be opened (${e.message}).`); });
    return () => { live = false; };
  }, [file]);
  return { text: t && t.file === file ? t.text : null, err };
}

export function DocsPage({ doc, target, open }: { doc: CadDoc; target: DocTarget; open: (t: DocTarget) => void }) {
  const [files, setFiles] = useState<string[]>([]);
  const [titles, setTitles] = useState<Record<string, string>>({});
  useEffect(() => {
    loadJson<{ files: string[]; passages: { file: string; doc: string }[] }>("copilot/kb.json").then((kb) => {
      setFiles(kb.files ?? []);
      const t: Record<string, string> = {};
      for (const p of kb.passages) t[p.file] ??= p.doc;
      setTitles(t);
    }).catch(() => undefined);
  }, []);
  const { text, err } = useText(target.file);
  const body = useRef<HTMLDivElement>(null);
  const control = (doc as unknown as { control?: Control }).control;

  // to the heading or the cited line, once the document is drawn
  useEffect(() => {
    const el = body.current;
    if (!el || !text) return;
    const at = target.line !== undefined
      ? [...el.querySelectorAll<HTMLElement>(".doc-hl")][0]
      : target.anchor ? el.querySelector<HTMLElement>(`#${CSS.escape(target.anchor)}`) : null;
    (at ?? el).scrollIntoView({ block: at ? "center" : "start", behavior: "smooth" });
  }, [text, target]);

  const toc = useMemo(() => (text ?? "").split("\n").map((l) => /^(#{2,3})\s+(.*)$/.exec(l)).filter(Boolean)
    .map((m) => ({ level: m![1].length, title: m![2].replace(/[`*]/g, ""), id: slug(m![2]) })), [text]);
  const lib = useMemo(() => {
    const g = new Map<string, string[]>();
    // a group's overview (its README) first
    const sorted = [...files].sort((a, b) => Number(!a.endsWith("README.md")) - Number(!b.endsWith("README.md")));
    for (const f of sorted) g.set(group(f), [...(g.get(group(f)) ?? []), f]);
    return ORDER.filter((k) => g.has(k)).map((k) => [k, g.get(k)!] as const);
  }, [files]);
  const follow = (href: string) => {
    const [path, anchor] = href.split("#");
    const dir = target.file.split("/").slice(0, -1).join("/");
    const file = path ? (path.startsWith("docs/") ? path : `${dir}/${path}`).replace(/\/\.\//g, "/") : target.file;
    open({ file, anchor });
  };
  const block = (kind: string, arg: string) => {
    if (!control) return null;
    if (kind === "plc-sfc") return <Sfc c={control} unit={arg} />;
    if (kind === "plc-architecture") return <Architecture c={control} />;
    if (kind === "plc-hardware") return <Network />;
    return null;
  };
  // an image's path, relative to its document, as the URL the knowledge base copied it to
  const asset = (path: string) => {
    if (/^https?:/.test(path)) return path;
    const parts = [...target.file.split("/").slice(0, -1), ...path.split("/")];
    const out: string[] = [];
    for (const p of parts) { if (p === "..") out.pop(); else if (p !== ".") out.push(p); }
    return `${BASE}copilot/${out.join("/")}`;
  };
  const name = (f: string) => titles[f] ?? f.split("/").pop()!.replace(/\.md$/, "");

  return (
    <div className="doc-layout">
      <nav className="doc-lib" aria-label="Documents">
        {lib.map(([g, fs]) => (
          <details key={g} open={fs.includes(target.file) || g === "PLC program" || g === "Vision QC"}>
            <summary>{g} <em>{fs.length}</em></summary>
            {fs.map((f) => (
              <button key={f} className={f === target.file ? "on" : ""} onClick={() => open({ file: f })}>{name(f)}</button>
            ))}
          </details>
        ))}
      </nav>
      <article className="doc-body db-card" ref={body}>
        <div className="doc-src">
          <span className="mono">{target.file}{target.line ? ` · line ${target.line}` : ""}</span>
          <a href={`${REPO}${target.file}${target.line ? `#L${target.line}` : ""}`} target="_blank" rel="noopener noreferrer">Open on GitHub ↗</a>
        </div>
        {err ? <p className="doc-muted">{err}</p> : text === null ? <p className="doc-muted">Opening…</p>
          : <Markdown src={text} hl={target.line} open={follow} block={block} asset={asset} />}
      </article>
      {toc.length > 2 && (
        <nav className="doc-toc" aria-label="On this page">
          <em>On this page</em>
          {toc.map((h) => (
            <button key={h.id} className={`l${h.level} ${h.id === target.anchor ? "on" : ""}`} onClick={() => open({ file: target.file, anchor: h.id })}>{h.title}</button>
          ))}
        </nav>
      )}
    </div>
  );
}
