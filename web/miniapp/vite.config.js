import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Served by FastAPI under /app/. Output is committed (web/miniapp/dist) so the
// server never needs Node — it just pulls and serves the built assets.
export default defineConfig({
  plugins: [react()],
  base: "/app/",
  build: {
    outDir: "dist",
    emptyOutDir: true,
    chunkSizeWarningLimit: 1500,
  },
});
