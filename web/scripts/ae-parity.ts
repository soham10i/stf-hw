// The browser's autoencoder against PyTorch on the samples autoencoder.py publishes.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { aeScore, decodeAe, f32 } from "../src/vision/ae";

const net = decodeAe(JSON.parse(readFileSync(join(process.argv[2], "autoencoder.json"), "utf8")));
let err = 0;
net.parity.images.forEach((b, i) => {
  const o = aeScore(net, f32(b));
  err = Math.max(err, Math.abs(o.score - net.parity.scores[i]) / net.parity.scores[i], Math.abs(o.mean - net.parity.means[i]) / net.parity.means[i]);
  console.log(`  sample ${i}: browser ${o.score.toExponential(4)} / ${o.mean.toExponential(4)}   torch ${net.parity.scores[i].toExponential(4)} / ${net.parity.means[i].toExponential(4)}`);
});
console.log(`largest relative difference ${err.toExponential(2)}`);
process.exit(err < 1e-3 ? 0 : 1);
