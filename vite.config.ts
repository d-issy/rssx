import { defineConfig } from "vite";
import { resolve } from "node:path";

export default defineConfig({
  build: {
    outDir: resolve(__dirname, "src/rssx/static/dist"),
    emptyOutDir: true,
    sourcemap: true,
    minify: "oxc",
    target: "es2020",
    lib: {
      entry: resolve(__dirname, "frontend/main.ts"),
      name: "rssx",
      formats: ["iife"],
      fileName: () => "app.js",
    },
  },
});
