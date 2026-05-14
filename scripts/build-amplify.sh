#!/bin/bash
# Packages the Next.js standalone build into the .amplify-hosting format
# required by Amplify WEB_COMPUTE. Run from the repo root after `next build`.
set -e

NEXT_DIR="frontend/.next"
PUBLIC_DIR="frontend/public"
OUT="frontend/.amplify-hosting"

rm -rf "$OUT"
mkdir -p "$OUT/compute/default"
mkdir -p "$OUT/static/_next/static"

# Standalone server + its node_modules
cp -r "$NEXT_DIR/standalone/." "$OUT/compute/default/"

# next build doesn't copy static assets into standalone — do it manually
cp -r "$NEXT_DIR/static/." "$OUT/compute/default/.next/static/"
cp -r "$PUBLIC_DIR/." "$OUT/compute/default/public/"

# CDN-served static assets (CloudFront serves these without hitting compute)
cp -r "$NEXT_DIR/static/." "$OUT/static/_next/static/"
cp -r "$PUBLIC_DIR/." "$OUT/static/"

cat > "$OUT/deploy-manifest.json" << 'MANIFEST'
{
  "version": 1,
  "routes": [
    {
      "path": "/_next/static/*",
      "target": { "kind": "Static" },
      "fallback": null
    },
    {
      "path": "/robots.txt",
      "target": { "kind": "Static" },
      "fallback": null
    },
    {
      "path": "/favicon.ico",
      "target": { "kind": "Static" },
      "fallback": null
    },
    {
      "path": "/*",
      "target": { "kind": "Compute", "src": "default" },
      "fallback": null
    }
  ],
  "computeResources": [
    {
      "name": "default",
      "runtime": "nodejs20.x",
      "entrypoint": "server.js"
    }
  ],
  "imageSettings": {}
}
MANIFEST

echo "✓ .amplify-hosting built successfully"
