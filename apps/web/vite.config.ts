import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Демо живёт на GitHub Pages по адресу https://<user>.github.io/Prorab/,
// поэтому база пути не корневая. Переопределяется переменной BASE_PATH.
export default defineConfig({
  base: process.env.BASE_PATH ?? "/Prorab/",
  plugins: [react()],
  build: { outDir: "dist", emptyOutDir: true },
});
