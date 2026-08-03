import { Canvas } from "@react-three/fiber";
import { useEffect, useState, useSyncExternalStore } from "react";
import { Factory } from "./scene/Factory";
import { connect } from "./socket";
import { store } from "./store";
import { ControlPanel } from "./ui/ControlPanel";
import { ErrorBoundary } from "./ui/ErrorBoundary";
import { Telemetry } from "./ui/Telemetry";
import type { SceneDescriptor } from "./types";

function useConn() {
  return useSyncExternalStore(store.subscribe, store.get);
}

export default function App() {
  const [scene, setScene] = useState<SceneDescriptor | null>(null);
  const [error, setError] = useState<string | null>(null);
  const conn = useConn();

  useEffect(() => {
    fetch("/layout")
      .then((r) => r.json())
      .then((d: SceneDescriptor) => {
        setScene(d);
        connect(); // open the socket only once the scene graph can be built
        // Nudge react-three-fiber's measure hook: in some embedded browsers the
        // ResizeObserver does not fire an initial callback, so the Canvas can
        // come up at 0x0 and never render. A resize event forces a remeasure.
        requestAnimationFrame(() => window.dispatchEvent(new Event("resize")));
      })
      .catch((e) => setError(String(e)));
  }, []);

  return (
    <div className="app">
      <header>
        <h1>Smart Tabletop Factory — Digital Twin</h1>
        <div className="conn">
          <span className={`dot ${conn.conn}`} />
          {conn.conn}
          {scene && <span className="fp">layout {scene.fingerprint}</span>}
        </div>
      </header>

      <div className="body">
        <div className="viewport">
          {error && <div className="error">Cannot reach the API: {error}</div>}
          {scene && (
            <ErrorBoundary>
              <Canvas
                shadows
                camera={{ position: [6, 4, 6], fov: 45 }}
                dpr={[1, 2]}
                // preserveDrawingBuffer lets the canvas be screenshotted/recorded
                // for the portfolio; negligible cost at this scene size.
                gl={{ preserveDrawingBuffer: true }}
              >
                <Factory scene={scene} />
              </Canvas>
            </ErrorBoundary>
          )}
        </div>

        <aside className="sidebar">
          {scene && <ControlPanel scene={scene} />}
          {scene && <Telemetry scene={scene} />}
        </aside>
      </div>
    </div>
  );
}
