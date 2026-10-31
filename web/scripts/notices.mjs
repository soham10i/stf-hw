// The third-party notices the built site carries (public/legal/third-party-notices.txt): every
// production package bundled into the pages, with its licence text - what MIT, BSD, Apache-2.0,
// ISC and the fonts' OFL ask for when their code is redistributed. Run before each build
// (package.json prebuild); dev-only tools are not shipped, so they are not listed.
import { execFileSync } from "node:child_process";
import { existsSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const out = join(root, "public/legal/third-party-notices.txt");
const LICENCE_FILE = /^(licen[cs]e|copying|notice|ofl)(\.|-|$)/i;

const dirs = execFileSync("npm", ["ls", "--omit=dev", "--all", "--parseable"], { cwd: root, encoding: "utf8" })
  .split("\n")
  .filter((d) => d && d !== root);

const seen = new Map();
for (const dir of dirs) {
  const pkgFile = join(dir, "package.json");
  if (!existsSync(pkgFile)) continue;
  const pkg = JSON.parse(readFileSync(pkgFile, "utf8"));
  const key = `${pkg.name}@${pkg.version}`;
  if (seen.has(key) || pkg.private) continue;
  const texts = readdirSync(dir)
    .filter((f) => LICENCE_FILE.test(f))
    .sort()
    .map((f) => readFileSync(join(dir, f), "utf8").trim());
  const licence = typeof pkg.license === "string" ? pkg.license : pkg.license?.type ?? "see text";
  seen.set(key, { key, licence, home: pkg.homepage ?? pkg.repository?.url ?? pkg.repository ?? "", texts });
}

const rows = [...seen.values()].sort((a, b) => a.key.localeCompare(b.key));
const head = [
  "Third-party software notices",
  "",
  "The pages of this site include the open-source packages below. Each is listed with its",
  "licence and, where the package ships it, the licence text with its copyright notice.",
  `${rows.length} packages.`,
  "",
];
const body = rows.map((r) =>
  [
    "=".repeat(78),
    `${r.key}  (${r.licence})`,
    typeof r.home === "string" && r.home ? r.home.replace(/^git\+/, "") : "",
    "-".repeat(78),
    r.texts.length ? r.texts.join("\n\n") : `Licensed under ${r.licence}; the package ships no licence file.`,
    "",
  ].filter((l, i) => i !== 2 || l).join("\n"),
);
writeFileSync(out, head.join("\n") + "\n" + body.join("\n"));
console.log(`third-party notices: ${rows.length} packages -> ${out}`);
