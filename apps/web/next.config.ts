import type { NextConfig } from "next";

const isGhPages = process.env.GITHUB_PAGES === "true";
const repo = "resolute";

const nextConfig: NextConfig = {
  output: "export",
  basePath: isGhPages ? `/${repo}` : "",
  assetPrefix: isGhPages ? `/${repo}/` : undefined,
  images: { unoptimized: true },
  trailingSlash: true,
};

export default nextConfig;
