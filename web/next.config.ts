import type { NextConfig } from "next";

// In production Caddy routes /api/* to the FastAPI service, so the browser talks
// to one origin and the session cookie stays first-party. The rewrite below does
// the same when the web app runs on its own (development, or without Caddy).
const apiUrl = process.env.API_INTERNAL_URL || "http://localhost:8000";

const nextConfig: NextConfig = {
  output: "standalone",
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${apiUrl}/api/:path*` }];
  },
};

export default nextConfig;
