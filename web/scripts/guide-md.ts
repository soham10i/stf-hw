// Writes docs/DASHBOARD_GUIDE.md from src/dashboard/guide.ts - the same text the dashboard's
// Guide button shows, so the two cannot drift apart.
//   npx esbuild scripts/guide-md.ts --bundle --platform=node --outfile=../.cache/guide-md.mjs && node ../.cache/guide-md.mjs
import { mkdirSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { GUIDE, TERMS } from "../src/dashboard/guide";

const GROUPS: [string, string[]][] = [
  ["Operate", ["overview", "production", "quality", "vision", "alarms", "copilot"]],
  ["Maintain", ["health", "maintenance", "ai"]],
  ["Analyse", ["month", "throughput", "scheduler", "energy", "carbon", "security", "hardening"]],
  ["Engineer", ["engineering", "validation", "data"]],
  ["Docs", ["docs-degradation"]],
];
const out: string[] = [
  "# Operations dashboard: user guide",
  "",
  "The dashboard (`dashboard.html`, the **Dashboard** button in the 3D twin) shows the cell's production, health, energy and",
  "security, from the twin's models. Every page opens with one line on what it is for; its **Guide** button shows the rest",
  "of that page's section of this document, **Ask** opens the copilot beside the page, and an **i** beside each card",
  "title says what the card shows.",
  "",
  "> Every number is simulated from the twin's models, not measured on a real machine. Values the models only assume",
  "> are marked *assumed* on the blueprint sheets.",
  "",
  "## Pages",
  "",
  ...GROUPS.flatMap(([g, ids]) => [`- **${g}**: ` + ids.map((id) => `[${GUIDE[id].title}](#${GUIDE[id].title.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/-$/, "")})`).join(" · ")]),
  "",
];
for (const [g, ids] of GROUPS) {
  out.push(`---`, ``, `## ${g}`, ``);
  for (const id of ids) {
    const p = GUIDE[id];
    out.push(`### ${p.title}`, "", p.what, "", "**How to read it**", "");
    p.read.forEach((r, i) => out.push(`${i + 1}. ${r}`));
    out.push("", "| Section | What it shows |", "|---|---|");
    for (const [k, v] of p.sections) out.push(`| ${k} | ${v} |`);
    out.push("", `*Data:* ${p.source}`, "");
  }
}
out.push("---", "", "## Terms", "", "| Term | Meaning |", "|---|---|");
for (const [k, v] of Object.entries(TERMS)) out.push(`| ${k} | ${v} |`);
out.push("", "*Generated from `web/src/dashboard/guide.ts` by `web/scripts/guide-md.ts`.*", "");
writeFileSync(new URL("../../docs/DASHBOARD_GUIDE.md", import.meta.url), out.join("\n"));
console.log(`wrote docs/DASHBOARD_GUIDE.md: ${Object.keys(GUIDE).length} pages, ${Object.keys(TERMS).length} terms`);

// One document per page for the chat's knowledge base (docs/assistant), each with the terms it
// uses: the chat sends the page's own document with every question asked on that page.
const dir = new URL("../../docs/assistant/", import.meta.url);
mkdirSync(dir, { recursive: true });
for (const f of readdirSync(dir).filter((x) => x.startsWith("dashboard-"))) rmSync(new URL(f, dir));
for (const [g, ids] of GROUPS) {
  for (const id of ids) {
    const p = GUIDE[id];
    // the retriever's compact entry point: the first two sentences of the page's "what"
    const brief = p.what.match(/[^.!?]+[.!?]+/g)?.slice(0, 2).join(" ").trim() ?? p.what;
    const md = [`# Dashboard: ${p.title}`, "", `Dashboard group: ${g}. Page id: \`${id}\`.`, "", p.what, "", "## In brief", "", brief, "", "## How to read it", ""];
    p.read.forEach((r, i) => md.push(`${i + 1}. ${r}`));
    md.push("", "## Sections", "");
    for (const [k, v] of p.sections) md.push(`### ${k}`, "", v, "");
    md.push("## Where the numbers come from", "", p.source, "", "Every number is simulated from the twin's models, not measured on a real machine.", "");
    if (p.terms.length) {
      md.push("## Terms", "");
      for (const t of p.terms) if (TERMS[t]) md.push(`- **${t}**: ${TERMS[t]}`);
      md.push("");
    }
    md.push(`*Generated from \`web/src/dashboard/guide.ts\`; edit the guide, not this file.*`, "");
    writeFileSync(new URL(`dashboard-${id}.md`, dir), md.join("\n"));
  }
}
console.log(`wrote docs/assistant/dashboard-*.md: ${GROUPS.flatMap(([, ids]) => ids).length} pages`);
