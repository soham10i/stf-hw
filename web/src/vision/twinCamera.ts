// The dashboard's end of the 3D twin's inspection camera (vision/photo.ts): it says it is
// watching, so the twin streams the camera's live view, and it receives each cookie's photo.
// The live view is drawn and dropped - only the latest frame is held, nothing is stored; the
// photos are what the twin's API stores, and what the inspection models judge here.
import { useEffect, useRef, useState } from "react";
import { VISION_CHANNEL } from "./channel";

export type TwinPhoto = { n: number; flavour: string; truth?: string; jpeg: Blob; empty: Blob | null; t: number };
type Msg = { type: "frame"; jpeg: Blob; t: number; lit: boolean } | ({ type: "photo" } & TwinPhoto);

/** Say "watching" every 2 s while the page is visible; the twin streams for 5 s after each. */
const WATCH_MS = 2000;

/** The twin's camera: its live view (the latest frame, as a bitmap) and its photos, as they come. */
export function useTwinCamera(onPhoto: (p: TwinPhoto) => void) {
  const [frame, setFrame] = useState<{ bmp: ImageBitmap; t: number; lit: boolean } | null>(null);
  const [fps, setFps] = useState(0);
  const photo = useRef(onPhoto);
  photo.current = onPhoto;
  useEffect(() => {
    let ch: BroadcastChannel;
    try { ch = new BroadcastChannel(VISION_CHANNEL); } catch { return; }
    const watch = () => { if (document.visibilityState === "visible") ch.postMessage({ type: "watch" }); };
    watch();
    const id = window.setInterval(watch, WATCH_MS);
    const times: number[] = [];
    ch.onmessage = async (e: MessageEvent<Msg>) => {
      const m = e.data;
      if (m?.type === "photo") photo.current(m);
      if (m?.type !== "frame") return;
      try {
        const bmp = await createImageBitmap(m.jpeg);
        setFrame((old) => { old?.bmp.close(); return { bmp, t: m.t, lit: m.lit }; });
        const now = performance.now();
        times.push(now);
        while (times.length && now - times[0] > 2000) times.shift();
        setFps(times.length / 2);
      } catch { /* a frame that would not decode */ }
    };
    return () => { window.clearInterval(id); ch.close(); };
  }, []);
  // the feed has stopped when no frame came for 3 s (the twin closed, or its tab hidden)
  const [, tick] = useState(0);
  useEffect(() => { const id = window.setInterval(() => tick((x) => x + 1), 1000); return () => window.clearInterval(id); }, []);
  const live = !!frame && Date.now() - frame.t < 3000;
  return { frame: live ? frame : null, fps: live ? fps : 0 };
}

/** A photo at the models' size: N x N x 3 (0..1, channel last), each pixel the mean of the
    photo's pixels it covers (the photo is a whole multiple of N). */
export async function toModelImage(jpeg: Blob, N: number): Promise<Float32Array> {
  const bmp = await createImageBitmap(jpeg);
  const W = bmp.width, k = Math.max(1, Math.round(W / N));
  const c = document.createElement("canvas");
  c.width = c.height = N * k;
  const g = c.getContext("2d")!;
  g.drawImage(bmp, 0, 0, N * k, N * k);
  bmp.close();
  const px = g.getImageData(0, 0, N * k, N * k).data;
  const img = new Float32Array(N * N * 3);
  for (let y = 0; y < N; y++) for (let x = 0; x < N; x++) for (let ch = 0; ch < 3; ch++) {
    let a = 0;
    for (let dy = 0; dy < k; dy++) for (let dx = 0; dx < k; dx++) a += px[((y * k + dy) * N * k + x * k + dx) * 4 + ch];
    img[(y * N + x) * 3 + ch] = a / (k * k * 255);
  }
  return img;
}

/** a pixel differs from the empty hood by more than this (any channel): it is the cookie's */
const DIFF = 0.06;

/** The photo as the models are given it. They were trained on images with belt all round the
    cookie (render.py); the hood has rails and walls there. So, as an inspection station does with
    a part on a fixture, the cookie is found against the reference image of the empty hood, and
    everything that is not cookie is set to the belt's own colour (its median under the lens, in
    the reference image); the grey target in the corner is kept, as the models divide by it.
    Without a reference image the photo goes in as taken. */
export async function prepare(p: { jpeg: Blob; empty: Blob | null }, N: number, ref: number) {
  const photo = await toModelImage(p.jpeg, N);
  if (!p.empty) return { img: photo, cookie: null as Uint8Array | null };
  const empty = await toModelImage(p.empty, N);
  const NN = N * N, cookie = new Uint8Array(NN);
  for (let i = 0; i < NN; i++) {
    let d = 0;
    for (let c = 0; c < 3; c++) d = Math.max(d, Math.abs(photo[i * 3 + c] - empty[i * 3 + c]));
    cookie[i] = d > DIFF ? 1 : 0;
  }
  // a lone pixel is noise, not cookie
  const lone = (y: number, x: number) => {
    let n = 0;
    for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) {
      const yy = y + dy, xx = x + dx;
      if ((dy || dx) && yy >= 0 && yy < N && xx >= 0 && xx < N) n += cookie[yy * N + xx];
    }
    return n < 2;
  };
  const clean = cookie.map((v, i) => (v && !lone(Math.floor(i / N), i % N) ? 1 : 0));
  // the belt's colour: the median of the reference image's middle half (the belt under the lens)
  const belt = [0, 1, 2].map((c) => {
    const v: number[] = [];
    for (let y = N / 4; y < (3 * N) / 4; y++) for (let x = 0; x < N; x++) v.push(empty[(y * N + x) * 3 + c]);
    v.sort((a, b) => a - b);
    return v[v.length >> 1];
  });
  const img = new Float32Array(photo.length);
  for (let i = 0; i < NN; i++) {
    const y = Math.floor(i / N), x = i % N, keep = clean[i] || (y < ref && x < ref);
    for (let c = 0; c < 3; c++) img[i * 3 + c] = keep ? photo[i * 3 + c] : belt[c];
  }
  return { img, cookie: clean };
}
