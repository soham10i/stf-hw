// The operator copilot's knowledge base - the project's reference documents split into passages
// under their headings, so an answer can quote one and say exactly where it is from: the document,
// the section, the file, the line and the heading's anchor. It indexes exactly docs/reference/
// (docs/README.md): plans, history and internal notes beside it are never retrieved. Every file
// there starts with front matter - title, scope, module, last_verified - which names the document,
// travels with each of its passages, and is checked here: a file without it fails the build.
// `index: false` keeps a file out (the generated full dashboard guide repeats the per-page ones).
//
// A table is split by rows, and every passage of it repeats the table's header, so a row read
// alone still says what its columns are. Each indexed document is also copied next to the index
// (public/copilot/<its path>, e.g. public/copilot/docs/reference/plc/03-units.md), so the
// dashboard's Docs page can open the passage an answer cites.
//   node .cache/copilot-kb.mjs ../docs public/copilot/kb.json
import { copyFileSync, mkdirSync, readFileSync, readdirSync, statSync, writeFileSync } from "node:fs";
import { dirname, join, relative } from "node:path";

const [docs, out] = process.argv.slice(2);
const MAX_WORDS = 140;
type Passage = { id: number; doc: string; path: string[]; text: string; file: string; line: number; anchor: string; module: string };
type Front = { title: string; scope: string; module: string; last_verified: string; generated_by?: string; index?: boolean };
const MODULES = new Set(["factory", "warehouse", "gripper-robot", "oven", "sorting-line", "machine", "plc", "twin", "dashboard",
  "guide", "maintenance", "vision", "process", "copilot", "operations", "architecture"]);
const passages: Passage[] = [];

/** Markdown to plain text: no tables' pipes, links keep their text, no emphasis marks. LaTeX
    ($...$, $$...$$) is kept as written, so an answer can quote an equation exactly. */
function plain(md: string) {
  const tex: string[] = [];
  const kept = md.replace(/\$\$[\s\S]+?\$\$|\$[^$\n]+\$/g, (m) => `\u0000${tex.push(m.replace(/\s+/g, " ")) - 1}\u0000`);
  return kept.replace(/<!--[\s\S]*?-->/g, " ").replace(/```[\s\S]*?```/g, " ").replace(/!\[([^\]]*)\]\([^)]+\)/g, "Figure: $1.").replace(/\[([^\]]+)\]\([^)]+\)/g, "$1").replace(/[*_`>#]/g, "")
    .replace(/\|/g, " ").replace(/^-{3,}$/gm, " ").replace(/^[ \t]*[-:| ]{3,}$/gm, " ").replace(/\s+/g, " ").trim()
    .replace(/\u0000(\d+)\u0000/g, (_, i) => tex[+i]);
}
/** A heading's anchor, as GitHub and the Docs page make it. */
export function slug(h: string) {
  return plain(h).toLowerCase().replace(/[^a-z0-9 _-]/g, "").trim().replace(/\s+/g, "-");
}
const cells = (row: string) => row.trim().replace(/^\||\|$/g, "").split(/(?<!\\)\|/).map((c) => plain(c.replace(/\\\|/g, "|")));

/** Every Markdown file under a folder, in path order. */
function walk(dir: string): string[] {
  return readdirSync(dir).sort().flatMap((x) => {
    const p = join(dir, x);
    return statSync(p).isDirectory() ? walk(p) : x.endsWith(".md") ? [p] : [];
  });
}
/** A document's front matter (key: value lines between --- fences; values may be quoted) and the
    number of lines it takes, so the passages' line numbers still point into the file. */
function frontMatter(src: string, file: string): { front: Front; lines: number } {
  const m = /^---\n([\s\S]*?)\n---\n/.exec(src);
  if (!m) throw new Error(`${file}: no front matter (docs/README.md)`);
  const kv: Record<string, string> = {};
  for (const line of m[1].split("\n")) {
    const at = /^([a-z_]+):\s*(.*)$/.exec(line);
    if (at) kv[at[1]] = /^".*"$/.test(at[2]) ? JSON.parse(at[2]) : at[2];
  }
  for (const k of ["title", "scope", "module", "last_verified"]) if (!kv[k]) throw new Error(`${file}: front matter has no ${k}`);
  if (!MODULES.has(kv.module)) throw new Error(`${file}: unknown module '${kv.module}'`);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(kv.last_verified)) throw new Error(`${file}: last_verified is not a date`);
  const front: Front = { title: kv.title, scope: kv.scope, module: kv.module, last_verified: kv.last_verified,
    ...(kv.generated_by ? { generated_by: kv.generated_by } : {}), ...(kv.index === "false" ? { index: false } : {}) };
  return { front, lines: m[0].split("\n").length - 1 };
}
const all = walk(join(docs, "reference"));
const fronts = new Map(all.map((f) => [f, frontMatter(readFileSync(f, "utf8"), f)]));
const files = all.filter((f) => fronts.get(f)!.front.index !== false);
const repo = join(docs, "..");
const copyTo = dirname(out);

for (const file of files) {
  const raw = readFileSync(file, "utf8");
  const rel = relative(repo, file);
  const { front, lines } = fronts.get(file)!;
  // the front matter's lines blanked, not dropped: every passage's line stays the file's own
  const src = "\n".repeat(lines) + raw.split("\n").slice(lines).join("\n");
  const doc = plain(front.title);
  const path: string[] = [];
  let anchor = "", startLine = 1;
  let buf: { line: number; text: string }[] = [];
  const push = (text: string, line: number) => {
    if (text.length > 40) passages.push({ id: passages.length, doc, path: [...path], text, file: rel, line, anchor, module: front.module });
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
// each document once, with what its front matter says (the passages carry only their module)
const documents = Object.fromEntries(files.map((f) => [relative(repo, f), fronts.get(f)!.front]));
writeFileSync(out, JSON.stringify({ passages, files: files.map((f) => relative(repo, f)), documents }));
console.log(`copilot knowledge base: ${passages.length} passages from ${new Set(passages.map((p) => p.doc)).size} documents -> ${out}`);
