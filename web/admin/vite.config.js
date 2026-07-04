import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Served by FastAPI behind the secret panel path at `/<secret>/v2/`. We use a
// RELATIVE base so the bundle never bakes the secret path in; the server injects
// `window.__PANEL_BASE__` (the secret prefix) into index.html at serve time and
// mounts the assets under `/<secret>/v2/assets`. Output is committed (dist) so
// the server never needs Node — it just serves the built files.
export default defineConfig({
  plugins: [react()],
  base: "./",
  build: {
    outDir: "dist",
    emptyOutDir: true,
    chunkSizeWarningLimit: 1500,
  },
});
