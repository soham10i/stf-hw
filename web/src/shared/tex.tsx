// LaTeX in Markdown, for the copilot's answers and the Docs page: $...$ and \(...\) inline,
// $$...$$ and \[...\] displayed. A dollar sign is only math when it reads like math - no space
// after the opening one, none before the closing one, no digit after it - so "$7 a month" stays
// text. KaTeX renders it; a formula it cannot parse is shown as written, never an error.
import katex from "katex";
import "katex/dist/katex.min.css";

export type Seg = { kind: "text" | "inline" | "display"; s: string };

const cache = new Map<string, string>();
export function texHtml(s: string, display: boolean) {
  const k = `${display ? "D" : "I"}${s}`;
  let h = cache.get(k);
  if (h === undefined) {
    h = katex.renderToString(s, {
      displayMode: display, throwOnError: false, strict: "ignore", output: "html",
      // the text can come from a model and from web pages: no \href/\url/\html* commands, and a
      // bounded macro expansion (a macro bomb cannot hang the tab)
      trust: false, maxExpand: 1000, maxSize: 20,
    });
    if (cache.size > 500) cache.clear();
    cache.set(k, h);
  }
  return h;
}

export function TeX({ s, display = false }: { s: string; display?: boolean }) {
  return <span className={display ? "tex-display" : "tex-inline"} dangerouslySetInnerHTML={{ __html: texHtml(s, display) }} />;
}

const MATH = /\$\$([\s\S]+?)\$\$|\\\[([\s\S]+?)\\\]|\\\(([\s\S]+?)\\\)|\$(?=[^\s$])((?:\\\$|[^$\n])+?)(?<=[^\s\\])\$(?!\d)/g;

/** A line of text cut into text and math. */
export function mathSplit(text: string): Seg[] {
  const out: Seg[] = [];
  let at = 0;
  for (const m of text.matchAll(MATH)) {
    if (m.index! > at) out.push({ kind: "text", s: text.slice(at, m.index) });
    const display = m[1] !== undefined || m[2] !== undefined;
    out.push({ kind: display ? "display" : "inline", s: (m[1] ?? m[2] ?? m[3] ?? m[4]).trim() });
    at = m.index! + m[0].length;
  }
  if (at < text.length) out.push({ kind: "text", s: text.slice(at) });
  return out;
}

/** Where a displayed formula that spans lines ends: `lines[i]` opens it ($$ or \[ without its
    closing on the same line). Returns [formula, index of the closing line] or null. */
export function displayBlock(lines: string[], i: number): [string, number] | null {
  const open = /^\s*(\$\$|\\\[)\s*(.*)$/.exec(lines[i]);
  if (!open) return null;
  const close = open[1] === "$$" ? "$$" : "\\]";
  if (open[2].includes(close)) return null;               // one line: inline handling draws it
  const body = [open[2]];
  for (let j = i + 1; j < lines.length; j++) {
    const k = lines[j].indexOf(close);
    if (k >= 0) {
      body.push(lines[j].slice(0, k));
      return lines[j].slice(k + close.length).trim() ? null : [body.join("\n").trim(), j];
    }
    body.push(lines[j]);
  }
  return null;
}
