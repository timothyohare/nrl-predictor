import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Do NOT add output: 'export' — breaks SSR/ISR and Googlebot gets an empty shell

  // Bake git SHA into the build so the footer can show which commit is deployed.
  // CODEBUILD_RESOLVED_SOURCE_VERSION is set automatically by Amplify on every build.
  // Falls back to 'local' when running locally.
  env: {
    GIT_SHA: (process.env.CODEBUILD_RESOLVED_SOURCE_VERSION || "local").slice(0, 7),
  },
};

export default nextConfig;
