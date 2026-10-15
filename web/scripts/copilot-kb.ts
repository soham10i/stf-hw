// Upgrade 17: the operator copilot's knowledge base - the project's documents split into
// passages under their headings, so an answer can quote one and say where it is from.
//   node .cache/copilot-kb.mjs ../docs public/copilot/kb.json
import { readFileSync, readdirSync, writeFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";

const [docs, out] = process.argv.slice(2);
const MAX_WORDS = 140;
type Passage = { id: number; doc: string; path: string[]; text: string };
const passages: Passage[] = [];

/** Markdown to plain text: no tables' pipes, links keep their text, no emphasis marks. */
function plain(md: string) {
  return md.replace(/```[\s\S]*?```/g, " ").replace(/\[([^\]]+)\]\([^)]+\)/g, "$1").replace(/[*_`>#]/g, "")
    .replace(/\|/g, " ").replace(/^-{3,}$/gm, " ").replace(/^[ \t]*[-:| ]{3,}$/gm, " ").replace(/\s+/g, " ").trim();
}

for (const f of readdirSync(docs).filter((x) => x.endsWith(".md")).sort()) {
  const doc = f.replace(/\.md$/, "");
  const path: string[] = [];
  let buf: string[] = [];
  const flush = () => {
    const words = plain(buf.join("\n")).split(" ").filter(Boolean);
    for (let i = 0; i < words.length; i += MAX_WORDS) {
      const text = words.slice(i, i + MAX_WORDS).join(" ");
      if (text.length > 40) passages.push({ id: passages.length, doc, path: [...path], text });
    }
    buf = [];
  };
  for (const line of readFileSync(join(docs, f), "utf8").split("\n")) {
    const m = /^(#{1,4})\s+(.*)$/.exec(line);
    if (m) {
      flush();
      path.length = m[1].length - 1;
      path[m[1].length - 1] = plain(m[2]);
    } else buf.push(line);
  }
  flush();
}
mkdirSync(dirname(out), { recursive: true });
writeFileSync(out, JSON.stringify({ passages }));
console.log(`copilot knowledge base: ${passages.length} passages from ${new Set(passages.map((p) => p.doc)).size} documents -> ${out}`);
