// The page scripts/edge-bench.mjs opens in headless Chrome: the TCN bench (src/edge/bench.ts) on the
// dashboard's month, the result left on window.__bench for the script to collect.
import type { Weights } from "../src/dashboard/ml";
import { bench } from "../src/edge/bench";

const w = window as unknown as { __bench?: unknown; __step?: string };
(async () => {
  try {
    const W: Weights = await (await fetch("ml/weights.json")).json();
    const M: { x: number[][] } = await (await fetch("ml/month_inputs.json")).json();
    w.__bench = await bench(W, M.x, { n: 400, tiles: [1, 2, 4, 8], onStep: (s) => (w.__step = s) });
  } catch (e) {
    w.__bench = { error: String(e) };
  }
})();
