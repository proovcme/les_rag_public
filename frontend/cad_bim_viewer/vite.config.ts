import { defineConfig } from "vite";

export default defineConfig({
  base: "/les/cad-bim-viewer/",
  build: {
    outDir: "dist",
    assetsDir: "assets",
    sourcemap: false,
  },
});
