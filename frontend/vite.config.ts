import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// A interface compilada vai para dentro do pacote Python (F1.H14): o wheel a
// leva junto e o usuário final não precisa de Node.
const destino = fileURLToPath(new URL("../src/wolfz/static", import.meta.url));

// Em desenvolvimento, o Vite repassa /api para a API local, que precisa estar
// no ar (python scripts/servidor_teste.py --port 8799).
const api = `http://127.0.0.1:${process.env.WOLFZ_PORT ?? "8799"}`;

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: destino,
    emptyOutDir: true,
    chunkSizeWarningLimit: 1500,
  },
  server: {
    port: 5173,
    strictPort: true,
    proxy: { "/api": { target: api, changeOrigin: true } },
  },
});
