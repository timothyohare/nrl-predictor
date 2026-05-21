import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Do NOT add output: 'export' — breaks SSR/ISR and Googlebot gets an empty shell

  // Bake git SHA into the build so the footer can show which commit is deployed.
  // CODEBUILD_RESOLVED_SOURCE_VERSION is set automatically by Amplify on every build.
  // Falls back to 'local' when running locally.
  env: {
    // AWS_COMMIT_ID is set automatically by Amplify on every build
    GIT_SHA: (process.env.AWS_COMMIT_ID || process.env.CODEBUILD_RESOLVED_SOURCE_VERSION || "local").slice(0, 7),
  },
};

export default nextConfig;
