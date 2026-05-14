import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Do NOT add output: 'export' — breaks SSR/ISR and Googlebot gets an empty shell
  output: "standalone",
};

export default nextConfig;
