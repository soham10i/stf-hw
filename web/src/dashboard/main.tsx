import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "../shared/theme.css";
import "../index.css";
import "./styles/shell.css";
import "./styles/charts.css";
import "./styles/analyse.css";
import "./styles/maintain.css";
import "./styles/vision.css";
import "./styles/chat.css";
import { Dashboard } from "./Dashboard";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Dashboard />
  </StrictMode>,
);
