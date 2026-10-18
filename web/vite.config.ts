import { defineConfig } from "vite";

export default defineConfig({
  server: { proxy: { "/api": "http://127.0.0.1:8000" } },
  build: {
    outDir: "../src/rslib/web",
    emptyOutDir: true,
    chunkSizeWarningLimit: 2000,
    rollupOptions: {
      input: {
        main: "index.html",
        workflows: "workflows.html",
        spectral: "spectral.html",
      },
    },
  },
});
