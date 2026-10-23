// ?perf=1: frame rate, frame time, draw calls, triangles, shader programs and the material pool,
// in a small box over the viewport - to see what a change to the scene costs while it runs.
import { useFrame, useThree } from "@react-three/fiber";
import { useEffect, useRef } from "react";
import { poolStats } from "./MaterialPool";
import { batchStats } from "./Batcher";

export const PERF = typeof window !== "undefined" && new URLSearchParams(window.location.search).get("perf") === "1";

export function PerfOverlay() {
  const gl = useThree((s) => s.gl);
  const box = useRef<HTMLDivElement | null>(null);
  const acc = useRef({ frames: 0, since: performance.now(), worst: 0, last: performance.now() });
  useEffect(() => {
    const d = document.createElement("div");
    d.style.cssText = "position:fixed;right:8px;top:64px;z-index:50;padding:6px 8px;border-radius:6px;" +
      "font:11px/1.45 ui-monospace,Menlo,monospace;white-space:pre;background:rgba(0,0,0,.72);color:#9fe;pointer-events:none";
    document.body.appendChild(d);
    box.current = d;
    return () => { d.remove(); };
  }, []);
  useFrame(() => {
    const a = acc.current, now = performance.now();
    a.frames++;
    a.worst = Math.max(a.worst, now - a.last);
    a.last = now;
    if (now - a.since < 500 || !box.current) return;
    const fps = (a.frames * 1000) / (now - a.since);
    const i = gl.info, p = poolStats.current;
    box.current.textContent =
      `${fps.toFixed(0)} fps  ${(1000 / fps).toFixed(1)} ms  worst ${a.worst.toFixed(0)} ms\n` +
      `draws ${i.render.calls}  tris ${(i.render.triangles / 1e6).toFixed(2)} M\n` +
      `programs ${i.programs?.length ?? 0}  geometries ${i.memory.geometries}  textures ${i.memory.textures}\n` +
      (p ? `materials: ${p.pooled} pooled into ${p.looks} looks, ${p.restored} kept own\n` : "material pool off\n") +
      (batchStats.current ? `batches: ${batchStats.current.batched} meshes in ${batchStats.current.batches} draws` : "batching off");
    a.frames = 0; a.since = now; a.worst = 0;
  });
  return null;
}
