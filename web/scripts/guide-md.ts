// Writes docs/DASHBOARD_GUIDE.md from src/dashboard/guide.ts - the same text the dashboard's
// Guide button shows, so the two cannot drift apart.
//   npx esbuild scripts/guide-md.ts --bundle --platform=node --outfile=../.cache/guide-md.mjs && node ../.cache/guide-md.mjs
import { writeFileSync } from "node:fs";
import { GUIDE, TERMS } from "../src/dashboard/guide";

const GROUPS: [string, string[]][] = [
  ["Operate", ["overview", "production", "quality", "alarms"]],
  ["Maintain", ["health", "maintenance", "ai"]],
  ["Analyse", ["month", "throughput", "energy", "security", "hardening"]],
  ["Engineer", ["engineering", "validation", "data"]],
];
const out: string[] = [
  "# Operations dashboard: user guide",
  "",
  "The dashboard (`dashboard.html`, the **Dashboard** button in the 3D twin) shows the cell's production, health, energy and",
  "security, from the twin's models. Every page has a **Guide** button that shows the section of this document for that",
  "page, and an **i** beside each card title that says what the card shows.",
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
