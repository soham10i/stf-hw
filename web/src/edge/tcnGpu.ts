/// <reference types="@webgpu/types" />
// Trustworthy maintenance T4: the remaining-life TCN (stf-cad/hbw/ml/model.py) as one hand-written
// WebGPU compute kernel - the same forward pass as dashboard/ml.ts, a whole window per workgroup.
//
// One workgroup takes one window (inputs x 48 orders) through all four dilated causal convolutions,
// the residual, the pooling and the heads without leaving workgroup memory: the input (NIN x 48),
// and two 32 x 48 buffers used in turn - x -> A (h1) -> B (h2) -> A (h3) -> B (h4 = relu(c4) + h2,
// in place: each output reads only its own h2). 3744 floats, inside WebGPU's 16 KB guarantee. The
// weights stay in one storage buffer every workgroup reads (they fit the GPU's caches).
//
// TILE: each thread computes TILE output channels at one time step, so an input value loaded from
// workgroup memory feeds TILE multiply-adds (TILE = 1 is the plain kernel). The roofline in
// docs/maintenance/trustworthy-edge.md is why that matters: the plain kernel does two loads per
// multiply-add and is limited by loads, not by arithmetic.
import type { Weights } from "../dashboard/ml";

const T = 48, CH = 32, WG = 128;

function shader(nin: number, tile: number) {
  const XO = 0, AO = nin * T, BO = AO + CH * T;
  return /* wgsl */ `
const T: u32 = ${T}u;
const CH: u32 = ${CH}u;
const NIN: u32 = ${nin}u;
const WG: u32 = ${WG}u;
const TILE: u32 = ${tile}u;
const XO: u32 = ${XO}u;
const AO: u32 = ${AO}u;
const BO: u32 = ${BO}u;
// packed weights: c1.w c1.b c2.w c2.b c3.w c3.b c4.w c4.b fc.w fc.b rul.w rul.b cls.w cls.b
const W1: u32 = 0u;
const B1: u32 = W1 + CH * NIN * 3u;
const W2: u32 = B1 + CH;
const B2: u32 = W2 + CH * CH * 3u;
const W3: u32 = B2 + CH;
const B3: u32 = W3 + CH * CH * 3u;
const W4: u32 = B3 + CH;
const B4: u32 = W4 + CH * CH * 3u;
const WF: u32 = B4 + CH;
const BF: u32 = WF + 64u * 64u;
const WR: u32 = BF + 64u;
const BR: u32 = WR + 64u;
const WC: u32 = BR + 1u;
const BC: u32 = WC + 3u * 64u;

struct Dims { n: u32, cap: f32, stride: u32, pad: u32 };
@group(0) @binding(0) var<storage, read> X: array<f32>;
@group(0) @binding(1) var<storage, read> Wt: array<f32>;
@group(0) @binding(2) var<storage, read_write> Y: array<f32>;
@group(0) @binding(3) var<uniform> D: Dims;

var<workgroup> buf: array<f32, ${BO + CH * T}>;
var<workgroup> z: array<f32, 64>;
var<workgroup> f: array<f32, 64>;

// dst[o, t] = relu(b[o] + sum_c sum_k w[o, c, k] src[c, t + k dil - 2 dil])  (+ dst[o, t] if res)
fn conv(src: u32, cin: u32, dst: u32, wo: u32, bo: u32, dil: u32, res: bool, lid: u32) {
  for (var i = lid; i < (CH / TILE) * T; i += WG) {
    let o0 = (i / T) * TILE;
    let t = i % T;
    var acc: array<f32, TILE>;
    for (var j = 0u; j < TILE; j++) { acc[j] = Wt[bo + o0 + j]; }
    for (var k = 0u; k < 3u; k++) {
      let tt = i32(t) + i32(k * dil) - i32(2u * dil);
      if (tt < 0) { continue; }                       // causal zero padding
      for (var c = 0u; c < cin; c++) {
        let x = buf[src + c * T + u32(tt)];           // one load ...
        for (var j = 0u; j < TILE; j++) {             // ... TILE multiply-adds
          acc[j] = fma(Wt[wo + ((o0 + j) * cin + c) * 3u + k], x, acc[j]);
        }
      }
    }
    for (var j = 0u; j < TILE; j++) {
      let at = dst + (o0 + j) * T + t;
      var v = max(acc[j], 0.0);
      if (res) { v += buf[at]; }
      buf[at] = v;
    }
  }
  workgroupBarrier();
}

@compute @workgroup_size(${WG})
fn main(@builtin(workgroup_id) wid: vec3<u32>, @builtin(local_invocation_index) lid: u32) {
  let b = wid.x + wid.y * D.stride;
  if (b >= D.n) { return; }                           // uniform per workgroup: barriers stay safe
  for (var i = lid; i < NIN * T; i += WG) { buf[XO + i] = X[b * NIN * T + i]; }
  workgroupBarrier();
  conv(XO, NIN, AO, W1, B1, 1u, false, lid);
  conv(AO, CH, BO, W2, B2, 2u, false, lid);
  conv(BO, CH, AO, W3, B3, 4u, false, lid);
  conv(AO, CH, BO, W4, B4, 8u, true, lid);
  if (lid < CH) {
    z[lid] = buf[BO + lid * T + T - 1u];
    var s = 0.0;
    for (var t = 0u; t < T; t++) { s += buf[BO + lid * T + t]; }
    z[CH + lid] = s / f32(T);
  }
  workgroupBarrier();
  if (lid < 64u) {
    var a = Wt[BF + lid];
    for (var i = 0u; i < 64u; i++) { a = fma(Wt[WF + lid * 64u + i], z[i], a); }
    f[lid] = max(a, 0.0);
  }
  workgroupBarrier();
  if (lid == 0u) {
    var r = Wt[BR];
    var l0 = Wt[BC]; var l1 = Wt[BC + 1u]; var l2 = Wt[BC + 2u];
    for (var i = 0u; i < 64u; i++) {
      r = fma(Wt[WR + i], f[i], r);
      l0 = fma(Wt[WC + i], f[i], l0);
      l1 = fma(Wt[WC + 64u + i], f[i], l1);
      l2 = fma(Wt[WC + 128u + i], f[i], l2);
    }
    let m = max(l0, max(l1, l2));
    let e0 = exp(l0 - m); let e1 = exp(l1 - m); let e2 = exp(l2 - m);
    let s = e0 + e1 + e2;
    Y[b * 4u] = D.cap / (1.0 + exp(-r));
    Y[b * 4u + 1u] = e0 / s; Y[b * 4u + 2u] = e1 / s; Y[b * 4u + 3u] = e2 / s;
  }
}`;
}

/** The weights in the kernel's order, one Float32Array. */
export function packWeights(W: Weights): Float32Array<ArrayBuffer> {
  const out: number[] = [];
  for (const c of W.conv) {
    for (const wo of c.w) for (const wi of wo) out.push(...wi);
    out.push(...c.b);
  }
  for (const l of [W.fc, W.rul, W.cls]) {
    for (const row of l.w) out.push(...row);
    out.push(...l.b);
  }
  return new Float32Array(out);
}

/** A window from dashboard/ml.ts (inputs x time) as one flat row of the kernel's input. */
export function flatten(x: Float32Array[], into: Float32Array, at: number) {
  for (let c = 0; c < x.length; c++) into.set(x[c], at + c * x[c].length);
}

export type GpuTcn = {
  /** n windows (n x NIN x 48, flat) -> n x [rul, p_healthy, p_degrading, p_critical] */
  run(x: Float32Array, n: number): Promise<Float32Array>;
  adapter: string;
  destroy(): void;
};

export async function gpuTcn(W: Weights, tile = 4): Promise<GpuTcn | null> {
  const gpu = (navigator as Navigator & { gpu?: GPU }).gpu;
  if (!gpu) return null;
  const adapter = await gpu.requestAdapter({ powerPreference: "high-performance" });
  if (!adapter) return null;
  const device = await adapter.requestDevice();
  const nin = W.inputs.length;
  const module = device.createShaderModule({ code: shader(nin, tile) });
  const info = await module.getCompilationInfo();
  const errs = info.messages.filter((m) => m.type === "error");
  if (errs.length) throw new Error(errs.map((m) => `${m.lineNum}: ${m.message}`).join("\n"));
  const pipeline = device.createComputePipeline({ layout: "auto", compute: { module, entryPoint: "main" } });
  const packed = packWeights(W);
  const wbuf = device.createBuffer({ size: packed.byteLength, usage: GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_DST });
  device.queue.writeBuffer(wbuf, 0, packed);
  const dims = device.createBuffer({ size: 16, usage: GPUBufferUsage.UNIFORM | GPUBufferUsage.COPY_DST });
  let cap = 0;
  let xbuf: GPUBuffer, ybuf: GPUBuffer, rbuf: GPUBuffer, group: GPUBindGroup;
  const grow = (n: number) => {
    if (n <= cap) return;
    if (cap) { xbuf.destroy(); ybuf.destroy(); rbuf.destroy(); }
    cap = Math.max(n, 2 * cap);
    xbuf = device.createBuffer({ size: cap * nin * T * 4, usage: GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_DST });
    ybuf = device.createBuffer({ size: cap * 16, usage: GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_SRC });
    rbuf = device.createBuffer({ size: cap * 16, usage: GPUBufferUsage.MAP_READ | GPUBufferUsage.COPY_DST });
    group = device.createBindGroup({
      layout: pipeline.getBindGroupLayout(0),
      entries: [{ binding: 0, resource: { buffer: xbuf } }, { binding: 1, resource: { buffer: wbuf } },
        { binding: 2, resource: { buffer: ybuf } }, { binding: 3, resource: { buffer: dims } }],
    });
  };
  const MAXX = 65535;
  return {
    adapter: [adapter.info?.vendor, adapter.info?.architecture, adapter.info?.description].filter(Boolean).join(" "),
    async run(x, n) {
      grow(n);
      device.queue.writeBuffer(xbuf, 0, x.buffer, x.byteOffset, n * nin * T * 4);
      const gx = Math.min(n, MAXX), gy = Math.ceil(n / MAXX);
      const d = new ArrayBuffer(16);
      new Uint32Array(d, 0, 1)[0] = n;
      new Float32Array(d, 4, 1)[0] = W.rul_cap;
      new Uint32Array(d, 8, 1)[0] = gx;
      device.queue.writeBuffer(dims, 0, d);
      const enc = device.createCommandEncoder();
      const pass = enc.beginComputePass();
      pass.setPipeline(pipeline);
      pass.setBindGroup(0, group);
      pass.dispatchWorkgroups(gx, gy);
      pass.end();
      enc.copyBufferToBuffer(ybuf, 0, rbuf, 0, n * 16);
      device.queue.submit([enc.finish()]);
      await rbuf.mapAsync(GPUMapMode.READ, 0, n * 16);
      const out = new Float32Array(rbuf.getMappedRange(0, n * 16).slice(0));
      rbuf.unmap();
      return out;
    },
    destroy() { device.destroy(); },
  };
}
