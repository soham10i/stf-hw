// The inspection camera's live view inside the twin: the belt under the lens in the colour hood,
// as the camera sees it, about 8 frames a second while this view is open (vision/photo.ts). The
// ring light flashes as a cookie crosses the lens and the photo is taken.
import { useEffect, useRef, useState } from "react";
import { cameraFrames, cameraWatch } from "../vision/photo";

export function CameraView({ size = 168 }: { size?: number }) {
  const img = useRef<HTMLImageElement>(null);
  const [lit, setLit] = useState(false);
  const [live, setLive] = useState(false);
  useEffect(() => {
    cameraWatch.local++;
    let url = "", last = 0;
    const on = (b: Blob, l: boolean) => {
      const next = URL.createObjectURL(b);
      if (img.current) img.current.src = next;
      if (url) URL.revokeObjectURL(url);
      url = next;
      last = Date.now();
      setLit(l);
      setLive(true);
    };
    cameraFrames.add(on);
    const id = window.setInterval(() => { if (Date.now() - last > 2000) setLive(false); }, 1000);
    return () => { cameraWatch.local--; cameraFrames.delete(on); window.clearInterval(id); if (url) URL.revokeObjectURL(url); };
  }, []);
  return (
    <figure className={`cam-view ${lit ? "lit" : ""}`} style={{ width: size }}>
      <img ref={img} alt="The inspection camera's live view of the sorting belt" width={size} height={size} />
      {!live && <span className="cam-wait">Starting the camera…</span>}
      <figcaption><i className={live ? "on" : ""} />{lit ? "Photographing the cookie" : live ? "Live · sorting belt" : "Camera"}</figcaption>
    </figure>
  );
}
