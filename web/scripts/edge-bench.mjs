// Trustworthy maintenance T4: the browser half of `make edge` - bundles the TCN bench
// (src/edge/bench.ts), serves it beside web/public on 127.0.0.1, runs it in headless Chrome with
// the GPU on (Metal on a Mac) and writes web/public/edge/browser.json.
//   node scripts/edge-bench.mjs            (from web/; needs Chrome and playwright-core)
import { build } from "esbuild";
import { createServer } from "node:http";
import { readFile, writeFile, mkdir } from "node:fs/promises";
import { extname, join, normalize } from "node:path";

const pub = new URL("../public/", import.meta.url).pathname;
const js = (await build({ entryPoints: [new URL("./edge-bench-page.ts", import.meta.url).pathname], bundle: true, format: "esm", write: false, logLevel: "warning" })).outputFiles[0].text;
const type = { ".json": "application/json", ".js": "text/javascript", ".html": "text/html" };
const server = createServer(async (req, res) => {
  const p = new URL(req.url, "http://x").pathname;
  if (p === "/") { res.writeHead(200, { "content-type": "text/html" }); return res.end('<!doctype html><script type="module" src="/bench.js"></script>'); }
  if (p === "/bench.js") { res.writeHead(200, { "content-type": "text/javascript" }); return res.end(js); }
  const f = normalize(join(pub, p));
  if (!f.startsWith(pub)) { res.writeHead(403); return res.end(); }
  try { const b = await readFile(f); res.writeHead(200, { "content-type": type[extname(f)] ?? "application/octet-stream" }); res.end(b); }
  catch { res.writeHead(404); res.end(); }
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const url = `http://127.0.0.1:${server.address().port}/`;
const { chromium } = await import("playwright-core");
const browser = await chromium.launch({ channel: "chrome", headless: true,
  args: ["--enable-unsafe-webgpu", "--enable-features=Vulkan", "--use-angle=metal", "--ignore-gpu-blocklist"] });
const page = await browser.newPage();
page.on("console", (m) => m.type() === "error" && console.error("page:", m.text()));
await page.goto(url);
let last = "";
for (;;) {
  const r = await page.evaluate(() => ({ done: window.__bench, step: window.__step }));
  if (r.step && r.step !== last) { console.log(" ", (last = r.step)); }
  if (r.done) {
    await mkdir(join(pub, "edge"), { recursive: true });
    await writeFile(join(pub, "edge", "browser.json"), JSON.stringify(r.done));
    console.log(JSON.stringify(r.done, null, 1));
    break;
  }
  await new Promise((s) => setTimeout(s, 500));
}
await browser.close();
server.close();
