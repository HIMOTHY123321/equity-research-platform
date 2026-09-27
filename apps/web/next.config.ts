import type { NextConfig } from "next";
import path from "node:path";

const nextConfig: NextConfig = {
  // Phase 16 (§78): minimal, production-ready Docker image -- copies only
  // the files the server actually needs into .next/standalone. Purely a
  // build-output shape change; `next dev` is unaffected.
  output: "standalone",
  turbopack: {
    root: path.join(__dirname, "../.."),
  },
};

export default nextConfig;
