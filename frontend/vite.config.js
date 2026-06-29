import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Прокси на FastAPI-бэкенд (порт 8000 по умолчанию).
const BACKEND = process.env.BACKEND_URL || "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": { target: BACKEND, changeOrigin: true },
      "/ws": { target: BACKEND.replace("http", "ws"), ws: true },
    },
  },
});
