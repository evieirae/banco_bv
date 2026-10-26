import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Build do SPA para ../static (servido pelo FastAPI). base relativo p/ funcionar
// sob o path do Databricks App. Proxy /api no dev local para o backend (porta 8000).
export default defineConfig({
  plugins: [react()],
  base: "./",
  build: {
    outDir: "../static",
    emptyOutDir: true,
  },
  server: {
    proxy: {
      // Alvo configurável por env: com mais de uma sessão/worktree rodando o app na mesma
      // máquina, a porta 8000 fica ocupada pela primeira. Suba a outra com
      // `APP_PORT=8001 ./local_app.sh serve back` e
      // `API_TARGET=http://localhost:8001 npm run dev -- --port 5174`.
      "/api": process.env.API_TARGET ?? "http://localhost:8000",
    },
  },
});
