import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The API runs on :8000; proxy REST and the WebSocket so the browser talks to
// a single origin and there are no CORS surprises in dev.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/layout": "http://localhost:8000",
      "/command": "http://localhost:8000",
      "/orders": "http://localhost:8000",
      "/health": "http://localhost:8000",
      "/ws": { target: "ws://localhost:8000", ws: true },
    },
  },
});
