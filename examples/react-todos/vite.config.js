import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In dev, /api goes to a local fastapi-todos; on bult the ingress does the same by path.
export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": "http://localhost:8000" } },
});
