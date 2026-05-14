# Amplify recreate plan

The current app `dmazwh64vi4cy` is in inconsistent state — was created as static "Web" then patched to `WEB_COMPUTE`, but `framework: "Web"` and SPA `customRules` remain. Amplify's Next.js adapter never runs, so `deploy-manifest.json` never gets generated correctly. Recreating cleanly will fix this.

## 1. Repo cleanup (Claude does this)

- [ ] Delete `amplify.yml`
- [ ] Delete `scripts/build-amplify.sh` (and `scripts/` if empty)
- [ ] Remove `output: "standalone"` from `frontend/next.config.ts`
- [ ] Commit and push

## 2. Delete the existing Amplify app (you do this)

- [ ] In Amplify console → app `nrl-predictor` → App settings → General → **Delete app**
- [ ] Confirm deletion

## 3. Create a fresh Amplify app (you do this)

- [ ] Amplify console → **New app → Host web app → GitHub**
- [ ] Select repo `timothyohare/nrl-predictor`, branch `main`
- [ ] On the build settings page:
  - [ ] Toggle on **"My app is a monorepo"** and set **App root** to `frontend`
  - [ ] Verify Amplify shows framework as **Next.js - SSR** (not "Web"). If it doesn't, stop and tell me.
  - [ ] Add environment variables:
    - `API_GATEWAY_URL` = `https://2jjj64x7ih.execute-api.ap-southeast-2.amazonaws.com`
    - `NEXT_PUBLIC_API_BASE_URL` = `https://2jjj64x7ih.execute-api.ap-southeast-2.amazonaws.com`
- [ ] Click **Save and deploy**

## 4. Verify the deployment

- [ ] Wait ~3 min for first build to complete
- [ ] `curl -si https://main.<new-app-id>.amplifyapp.com/ | head -3` — expect `HTTP/2 200`, NOT `server: AmazonS3`
- [ ] Open the URL in a browser, confirm the home page renders

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
