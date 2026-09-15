import { defineConfig } from "electron-vite";
import react from "@vitejs/plugin-react";
import { resolve } from "node:path";
export default defineConfig({
  main: {
    build: { rollupOptions: { input: resolve("electron/main/index.ts") } },
  },
  preload: {
    build: {
      externalizeDeps: false,
      rollupOptions: { input: resolve("electron/preload/index.ts") },
    },
  },
  renderer: {
    root: ".",
    plugins: [react()],
    server: { host: "127.0.0.1", port: 5173, strictPort: true },
    build: { rollupOptions: { input: resolve("index.html") } },
  },
});
