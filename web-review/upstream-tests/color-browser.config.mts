import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { execFileSync } from "node:child_process";
import upstream from "./vitest.config.mts";

const commit = execFileSync("git", ["-c", `safe.directory=${process.cwd().replaceAll("\\", "/")}`, "rev-parse", "HEAD"], { encoding: "utf8" }).trim();
export default defineConfig({
  resolve: upstream.resolve,
  plugins: [react()],
  define: { __GEUL_COMMIT__: JSON.stringify(commit) },
  optimizeDeps: { entries: ["geul-color-browser.html"] },
  server: { host: "127.0.0.1", port: 56680, strictPort: true, open: false },
  // Real browser and original sources; no original test setup or app backend.
  envFile: false,
});
