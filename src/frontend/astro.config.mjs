import { defineConfig } from "astro/config";

// El backend (FastAPI) corre aparte, en el puerto 8787. En dev, Vite hace de
// proxy de /api hacia ahi para que el frontend solo hable con su propio
// origen (sin lidiar con CORS ni con URLs distintas por entorno).
export default defineConfig({
  server: { port: 4321 },
  vite: {
    server: {
      proxy: {
        "/api": {
          target: "http://127.0.0.1:8787",
          changeOrigin: true,
        },
      },
    },
  },
});
