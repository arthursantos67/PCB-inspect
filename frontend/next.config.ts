import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // `standalone` emits a self-contained server (.next/standalone/server.js) carrying only the
  // dependencies actually imported, which is what the production image ships — no source tree,
  // no full node_modules, no `next` CLI at runtime. It is opt-in through the environment rather
  // than always on because it changes what `next build` writes to disk, and the CI/e2e jobs
  // (`npm run build` + `npm run start`) want the ordinary output. Set by frontend/Dockerfile.
  output: process.env.NEXT_OUTPUT_STANDALONE === "1" ? "standalone" : undefined,
};

export default nextConfig;
