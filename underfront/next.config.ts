import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  async rewrites() {
    const origin = process.env.BACKEND_ORIGIN?.replace(/\/+$/, "");
    return origin ? [{ source: "/v1/:path*", destination: `${origin}/v1/:path*` }] : [];
  },
};

export default nextConfig;
