# Amplify recreate plan

The current app `dmazwh64vi4cy` is in inconsistent state — was created as static "Web" then patched to `WEB_COMPUTE`, but `framework: "Web"` and SPA `customRules` remain. Amplify's Next.js adapter never runs, so `deploy-manifest.json` never gets generated correctly. Recreating cleanly will fix this.

## 1. Repo cleanup (Claude does this) — DONE

- [x] Delete `amplify.yml`
- [x] Delete `scripts/build-amplify.sh` (and `scripts/` if empty)
- [x] Remove `output: "standalone"` from `frontend/next.config.ts`
- [x] Commit and push (commit `bf4ab9d`)

## 2. Delete the existing Amplify app (you do this) — DONE

- [x] App `dmazwh64vi4cy` deleted

## 3. Create a fresh Amplify app (you do this) — DONE

- [x] New app created with ID `d60x8viwfcqtj`
- [x] Framework correctly detected as **Next.js - SSR**
- [x] Env vars set
- [x] Deploy succeeded on first try

## 4. Verify the deployment — DONE

- [x] `https://main.d60x8viwfcqtj.amplifyapp.com/` returns HTTP 200 with `x-powered-by: Next.js`
- [x] Dynamic route `/predictions/12` SSR-renders correctly

## 5. Reconnect custom domain

- [ ] In new Amplify app → Domain management → Add domain → `ohare.id.au` → subdomain `nrl-predictor`
- [ ] Wait for Amplify to display the new CloudFront target CNAME
- [ ] In Route 53 hosted zone `ohare.id.au`: update CNAME record `nrl-predictor` to point to the new CloudFront target
- [ ] Wait for SSL cert validation (5–30 min)
- [ ] `curl -si https://nrl-predictor.ohare.id.au/ | head -3` — expect `HTTP/2 200`

---

## Rollback if Amplify monorepo detection fails

If step 3 shows framework as "Web" instead of "Next.js - SSR" even after enabling monorepo with root `frontend`, then Amplify Gen 1 can't auto-detect Next.js in a subdirectory for this repo. Two fallback options:

- **A. Restructure the repo** to put Next.js at the root (move `frontend/*` to `/`, move Python code to a subdirectory)
- **B. Host the frontend elsewhere** — Vercel (free, native Next.js, zero config) or AWS App Runner with a container

Tell me which you want and I'll do the work.
