// verified: /vercel/next.js/v15.1.11 (May 2026)
// `output: 'standalone'` enables minimal Docker images by tracing only the
// files needed at runtime into .next/standalone. We don't ship a production
// build in Step 1 (dev only), but the option is set for later steps.
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
};

export default nextConfig;
