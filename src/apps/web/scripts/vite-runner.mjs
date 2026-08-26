import { rm } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { build, createServer, preview } from "vite";

const command = process.argv[2] ?? "build";
const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const webRoot = path.resolve(scriptDir, "..");
const repositoryRoot = path.resolve(webRoot, "..", "..", "..");
const outputDir = path.resolve(webRoot, "..", "..", "..", "build", "web");

const sharedConfig = {
  configFile: false,
  envDir: repositoryRoot,
  // The maptiles key is intentionally public and restricted by referrer in
  // Goong Console. The REST GOONG_API_KEY remains backend-only.
  envPrefix: ["VITE_", "GOONG_MAPTILES_KEY"],
  plugins: [react()],
  build: {
    outDir: outputDir,
    emptyOutDir: false,
  },
  server: {
    port: 5173,
  },
  preview: {
    port: 4173,
  },
};

if (command === "dev") {
  const server = await createServer(sharedConfig);
  await server.listen();
  server.printUrls();
} else if (command === "build") {
  // Remove stale bundles first, then let Vite write all generated assets.
  // Map renderers emit dedicated worker modules that are not reliably
  // represented in the in-memory Rollup result returned by write:false.
  await rm(outputDir, { recursive: true, force: true });
  await build(sharedConfig);
} else if (command === "preview") {
  const server = await preview(sharedConfig);
  server.printUrls();
} else {
  throw new Error(`Unsupported Vite command: ${command}`);
}
