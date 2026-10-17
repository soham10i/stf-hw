// The Docs page's Markdown: headings with anchors, paragraphs, lists, tables, code, links and
// emphasis - and fenced blocks a document names (```plc-sfc crane```) drawn by a component. Each
// block and table row carries the source lines it came from, so a cited passage (file + line)
// is found and highlighted exactly.
import type { ReactNode } from "react";

export type Block = (kind: string, arg: string) => ReactNode | null;

/** A heading's anchor: the same as the knowledge base's (web/scripts/copilot-kb.ts) and GitHub's. */
export function slug(h: string) {
  return h.replace(/\[([^\]]+)\]\([^)]+\)/g, "$1").replace(/[*_`>#]/g, "").toLowerCase()
    .replace(/[^a-z0-9 _-]/g, "").trim().replace(/\s+/g, "-");
}

function inline(s: string, open: (href: string) => void, key = 0): ReactNode[] {
  const parts = s.split(/(`[^`]+`|\*\*[^*]+\*\*|\*[^*\s][^*]*\*|\[[^\]]+\]\([^)\s]+\))/g);
  return parts.map((p, i) => {
    const k = `${key}-${i}`;
    if (p.startsWith("`") && p.endsWith("`") && p.length > 1) return <code key={k}>{p.slice(1, -1)}</code>;
    if (p.startsWith("**") && p.endsWith("**")) return <b key={k}>{p.slice(2, -2)}</b>;
    if (p.startsWith("*") && p.endsWith("*") && p.length > 2) return <em key={k}>{p.slice(1, -1)}</em>;
    const m = /^\[([^\]]+)\]\(([^)\s]+)\)$/.exec(p);
    if (m) {
      const href = m[2];
      if (/^https?:\/\//.test(href)) return <a key={k} href={href} target="_blank" rel="noopener noreferrer">{m[1]}</a>;
      return <a key={k} href={`#${href}`} onClick={(e) => { e.preventDefault(); open(href); }}>{m[1]}</a>;
    }
    return p.replace(/\\\|/g, "|");
  });
}

const row = (l: string) => l.trim().replace(/^\||\|$/g, "").split(/(?<!\\)\|/).map((c) => c.trim());

/** Render `src`; `hl` is the source line to highlight (a citation's), `open` follows a relative link. */
export function Markdown({ src, hl, open, block }: { src: string; hl?: number; open: (href: string) => void; block: Block }) {
  const lines = src.split("\n");
  const out: ReactNode[] = [];
  const mark = (a: number, b: number) => (hl !== undefined && hl >= a && hl <= b ? "doc-hl" : undefined);
  let i = 0;
  while (i < lines.length) {
    const line = lines[i], n = i + 1;
    const fence = /^```\s*([\w-]*)\s*(.*)$/.exec(line);
    if (fence) {
      let j = i + 1;
      while (j < lines.length && !/^```/.test(lines[j])) j++;
      const body = lines.slice(i + 1, j).join("\n");
      const drawn = fence[1] ? block(fence[1], fence[2].trim()) : null;
      out.push(drawn ? <div key={n} className="doc-figure" data-line={n}>{drawn}</div>
        : <pre key={n} className={mark(n, j + 1)} data-line={n}><code>{body}</code></pre>);
      i = j + 1;
      continue;
    }
    const h = /^(#{1,4})\s+(.*)$/.exec(line);
    if (h) {
      const L = `h${Math.min(4, h[1].length + 1)}` as "h2";
      out.push(<L key={n} id={slug(h[2])} className={mark(n, n)} data-line={n}>{inline(h[2], open, n)}</L>);
      i++;
      continue;
    }
    if (/^\s*\|/.test(line) && /^\s*\|[\s|:-]+\|\s*$/.test(lines[i + 1] ?? "")) {
      const head = row(line);
      let j = i + 2;
      const rows: { n: number; c: string[] }[] = [];
      for (; j < lines.length && /^\s*\|/.test(lines[j]); j++) rows.push({ n: j + 1, c: row(lines[j]) });
      out.push(
        <div key={n} className="doc-table" data-line={n}><table>
          <thead><tr>{head.map((c, k) => <th key={k}>{inline(c, open, k)}</th>)}</tr></thead>
          <tbody>{rows.map((r) => <tr key={r.n} className={mark(r.n, r.n)} data-line={r.n}>{r.c.map((c, k) => <td key={k}>{inline(c, open, k)}</td>)}</tr>)}</tbody>
        </table></div>,
      );
      i = j;
      continue;
    }
    const li = /^(\s*)([-*]|\d+[.)])\s+(.*)$/.exec(line);
    if (li) {
      const ordered = /\d/.test(li[2]);
      const items: { n: number; text: string }[] = [];
      let j = i;
      for (; j < lines.length; j++) {
        const m = /^(\s*)([-*]|\d+[.)])\s+(.*)$/.exec(lines[j]);
        if (m && /\d/.test(m[2]) === ordered) items.push({ n: j + 1, text: m[3] });
        else if (/^\s{2,}\S/.test(lines[j]) && items.length) items[items.length - 1].text += " " + lines[j].trim();
        else break;
      }
      const L = ordered ? "ol" : "ul";
      out.push(<L key={n} data-line={n}>{items.map((it, k) => <li key={it.n} className={mark(it.n, (items[k + 1]?.n ?? j + 1) - 1)}>{inline(it.text, open, it.n)}</li>)}</L>);
      i = j;
      continue;
    }
    if (!line.trim()) { i++; continue; }
    // a paragraph: until a blank line or another block
    let j = i;
    const para: string[] = [];
    while (j < lines.length && lines[j].trim() && !/^(#{1,4}\s|```|\s*\||\s*([-*]|\d+[.)])\s)/.test(lines[j])) para.push(lines[j++]);
    if (!para.length) { para.push(lines[j++]); }
    out.push(<p key={n} className={mark(n, j)} data-line={n}>{inline(para.join(" "), open, n)}</p>);
    i = j;
  }
  return <>{out}</>;
}
