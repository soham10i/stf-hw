// The browser's CNN against PyTorch on the published test sheet (vision/train.py: parity).
// The sheet is a PNG; Node has no image decoder, so the PNG written by render.png
// (8-bit RGB, filter 0, one zlib stream) is read back here directly.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { inflateSync } from "node:zlib";
import { decode, forward, tile } from "../src/vision/cnn";

const dir = process.argv[2];
const net = decode(JSON.parse(readFileSync(join(dir, "weights.json"), "utf8")));
const res = JSON.parse(readFileSync(join(dir, "results.json"), "utf8"));
const png = readFileSync(join(dir, "test.png"));
const W = png.readUInt32BE(16), H = png.readUInt32BE(20);
const idat: Buffer[] = [];
for (let p = 8; p < png.length;) {
  const len = png.readUInt32BE(p), type = png.toString("ascii", p + 4, p + 8);
  if (type === "IDAT") idat.push(png.subarray(p + 8, p + 8 + len));
  p += 12 + len;
}
const raw = inflateSync(Buffer.concat(idat)), rgba = new Uint8ClampedArray(W * H * 4);
for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
  const s = y * (W * 3 + 1) + 1 + x * 3, d = (y * W + x) * 4;
  rgba[d] = raw[s]; rgba[d + 1] = raw[s + 1]; rgba[d + 2] = raw[s + 2]; rgba[d + 3] = 255;
}
let err = 0;
const t0 = Date.now();
res.sheet.labels.forEach((lb: { torch_flavour: number[]; torch_condition: number[] }, k: number) => {
  const o = forward(net, tile(rgba, W, res.sheet.cols, res.sheet.tile, k));
  lb.torch_flavour.forEach((v, i) => (err = Math.max(err, Math.abs(v - o.flavourLogits[i]))));
  lb.torch_condition.forEach((v, i) => (err = Math.max(err, Math.abs(v - o.conditionLogits[i]))));
});
process.stdout.write(JSON.stringify({ max_abs_err: err, images: res.sheet.labels.length, ms_per_image: (Date.now() - t0) / res.sheet.labels.length }));
