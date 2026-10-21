import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "@fontsource-variable/geist";
import "@fontsource-variable/geist-mono";
import "../shared/theme.css";
import "../index.css";
import "./styles/shell.css";
import "./styles/charts.css";
import "./styles/analyse.css";
import "./styles/maintain.css";
import "./styles/vision.css";
import "./styles/chat.css";
import "./styles/docs.css";
import "./styles/consent.css";
import "../shared/studio.css";
import { Dashboard } from "./Dashboard";
import { applyTheme } from "../shared/theme";

// the saved theme on the document before the first render: no flash of the other one
applyTheme();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Dashboard />
  </StrictMode>,
);
