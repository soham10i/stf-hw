// The operator copilot's knowledge base - the project's documents split into passages under
// their headings, so an answer can quote one and say exactly where it is from: the document, the
// section, the file, the line and the heading's anchor. Three sources: the project documents
// (docs/*.md), the PLC reference (docs/plc/, written from the program by `make plc-docs`) and the
// assistant's per-section documents (docs/assistant/), cited by their titles. DASHBOARD_GUIDE.md
// is left out: docs/assistant holds the same text, one document per page.
//
// A table is split by rows, and every passage of it repeats the table's header, so a row read
// alone still says what its columns are. Each indexed document is also copied next to the index
// (public/copilot/<its path>, e.g. public/copilot/docs/plc/03-units.md), so the dashboard's Docs page can open the passage an answer cites.
//   node .cache/copilot-kb.mjs ../docs public/copilot/kb.json
import { copyFileSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { dirname, join, relative } from "node:path";

const [docs, out] = process.argv.slice(2);
const MAX_WORDS = 140;
type Passage = { id: number; doc: string; path: string[]; text: string; file: string; line: number; anchor: string };
const passages: Passage[] = [];

/** Markdown to plain text: no tables' pipes, links keep their text, no emphasis marks. LaTeX
    ($...$, $$...$$) is kept as written, so an answer can quote an equation exactly. */
function plain(md: string) {
  const tex: string[] = [];
  const kept = md.replace(/\$\$[\s\S]+?\$\$|\$[^$\n]+\$/g, (m) => `\u0000${tex.push(m.replace(/\s+/g, " ")) - 1}\u0000`);
  return kept.replace(/```[\s\S]*?```/g, " ").replace(/!\[([^\]]*)\]\([^)]+\)/g, "Figure: $1.").replace(/\[([^\]]+)\]\([^)]+\)/g, "$1").replace(/[*_`>#]/g, "")
    .replace(/\|/g, " ").replace(/^-{3,}$/gm, " ").replace(/^[ \t]*[-:| ]{3,}$/gm, " ").replace(/\s+/g, " ").trim()
    .replace(/\u0000(\d+)\u0000/g, (_, i) => tex[+i]);
}
/** A heading's anchor, as GitHub and the Docs page make it. */
export function slug(h: string) {
  return plain(h).toLowerCase().replace(/[^a-z0-9 _-]/g, "").trim().replace(/\s+/g, "-");
}
const cells = (row: string) => row.trim().replace(/^\||\|$/g, "").split(/(?<!\\)\|/).map((c) => plain(c.replace(/\\\|/g, "|")));

const SKIP = new Set(["DASHBOARD_GUIDE.md", "README.md"]);
const md = (dir: string, keepReadme = false) =>
  readdirSync(join(docs, dir)).filter((x) => x.endsWith(".md") && (keepReadme || !SKIP.has(x))).sort().map((f) => join(docs, dir, f));
const files = [...md(""), ...md("plc", true), ...md("vision", true), ...md("maintenance", true), ...md("copilot", true), ...md("process", true), ...md("assistant")];
const repo = join(docs, "..");
const copyTo = dirname(out);

for (const file of files) {
  const src = readFileSync(file, "utf8");
  const rel = relative(repo, file);
  const title = /^#\s+(.+)$/m.exec(src)?.[1];
  const doc = (file.includes("/assistant/") || file.includes("/plc/") || file.includes("/vision/") || file.includes("/maintenance/") || file.includes("/copilot/") || file.includes("/process/")) && title ? plain(title) : file.split("/").pop()!.replace(/\.md$/, "");
  const path: string[] = [];
  let anchor = "", startLine = 1;
  let buf: { line: number; text: string }[] = [];
  const push = (text: string, line: number) => {
    if (text.length > 40) passages.push({ id: passages.length, doc, path: [...path], text, file: rel, line, anchor });
  };
  const flush = () => {
    // prose in passages of MAX_WORDS; a table in groups of rows, each with the header
    let prose: { line: number; text: string }[] = [];
    const flushProse = () => {
      const words = plain(prose.map((p) => p.text).join("\n")).split(" ").filter(Boolean);
      for (let i = 0; i < words.length; i += MAX_WORDS) push(words.slice(i, i + MAX_WORDS).join(" "), prose[0]?.line ?? startLine);
      prose = [];
    };
    for (let i = 0; i < buf.length; i++) {
      const isRow = (k: number) => k < buf.length && /^\s*\|/.test(buf[k].text);
      if (isRow(i) && isRow(i + 1) && /^\s*\|[\s|:-]+\|\s*$/.test(buf[i + 1].text)) {
        flushProse();
        const head = cells(buf[i].text);
        let j = i + 2, group: string[] = [], groupLine = buf[j]?.line ?? buf[i].line, words = 0;
        const emit = () => {
          if (group.length) push(`${head.join(" | ")}: ${group.join("; ")}`, groupLine);
          group = []; words = 0;
        };
        for (; isRow(j); j++) {
          const row = cells(buf[j].text).map((c, k) => (head[k] ? `${head[k]} ${c}` : c)).join(", ");
          const w = row.split(" ").length;
          if (words + w > MAX_WORDS && group.length) { emit(); groupLine = buf[j].line; }
          group.push(row); words += w;
        }
        emit();
        i = j - 1;
      } else prose.push(buf[i]);
    }
    flushProse();
    buf = [];
  };
  src.split("\n").forEach((line, n) => {
    const m = /^(#{1,4})\s+(.*)$/.exec(line);
    if (m) {
      flush();
      path.length = m[1].length - 1;
      path[m[1].length - 1] = plain(m[2]);
      anchor = slug(m[2]);
      startLine = n + 1;
    } else buf.push({ line: n + 1, text: line });
  });
  flush();
  mkdirSync(dirname(join(copyTo, rel)), { recursive: true });
  copyFileSync(file, join(copyTo, rel));
  // and the images it shows, at their place relative to it
  for (const m of src.matchAll(/!\[[^\]]*\]\(([^)\s]+)\)/g)) {
    if (/^https?:/.test(m[1])) continue;
    const img = join(dirname(file), m[1]);
    const to = join(copyTo, relative(repo, img));
    mkdirSync(dirname(to), { recursive: true });
    try { copyFileSync(img, to); } catch { console.warn(`  missing image ${relative(repo, img)} (in ${rel})`); }
  }
}
mkdirSync(dirname(out), { recursive: true });
writeFileSync(out, JSON.stringify({ passages, files: files.map((f) => relative(repo, f)) }));
console.log(`copilot knowledge base: ${passages.length} passages from ${new Set(passages.map((p) => p.doc)).size} documents -> ${out}`);
