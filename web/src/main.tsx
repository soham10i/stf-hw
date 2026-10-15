import ReactDOM from "react-dom/client";
import App from "./twin/App";
import "./shared/theme.css";
import "./index.css";
import "./twin/twin.css";

// No StrictMode: its dev-only double mount/unmount races react-three-fiber's
// async WebGL init and can leave the Canvas with a dead GL context (the renderer
// never attaches). The rest of the app is StrictMode-clean; this is purely to
// keep the 3D canvas reliable in development.
ReactDOM.createRoot(document.getElementById("root")!).render(<App />);
