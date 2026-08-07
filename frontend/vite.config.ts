import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In dev, proxy /api and /media to the FastAPI backend so the app runs same-origin
// (mirrors the nginx proxy used in production). Override target with VITE_DEV_BACKEND.
const backend = process.env.VITE_DEV_BACKEND || "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: backend, changeOrigin: true, rewrite: (p) => p.replace(/^\/api/, "") },
      "/media": { target: backend, changeOrigin: true },
    },
  },
});
