# Vinci playground

A public page where anyone can make a few free images in the browser, then get pointed at the full studio. It is the "try it" link for the README and launch posts.

- Images run on Workers AI (`@cf/black-forest-labs/flux-1-schnell`, 1024x1024, 4 steps) and come back inline. Nothing is stored.
- Each prompt is checked with Llama Guard (`@cf/meta/llama-guard-3-8b`) first. If the check fails or errors, the prompt is refused.
- Limits: `PER_VISITOR_DAILY` images per visitor (default 3) and `GLOBAL_DAILY` images for everyone (default 20,000). Visitors are counted by a salted hash of their IP; raw IPs are never stored. Failed generations do not count.
- Optional Turnstile: set `TURNSTILE_SITE_KEY` (var) and `TURNSTILE_SECRET` (secret) to add the bot check.

## Cost

Per image, from the Workers AI price list (Nov 2026): FLUX.1 Schnell at 1024x1024 and 4 steps is about $0.0006 to $0.002, plus well under $0.001 for the safety check. At the default global cap of 20,000 images a day, the worst case is about $40 a day. Lower `GLOBAL_DAILY` to cap it harder.

## Deploy

```bash
cd deploy/playground
npm ci
npx wrangler kv namespace create QUOTA        # paste the id into wrangler.jsonc
npx wrangler secret put QUOTA_SALT            # any random string, e.g. openssl rand -hex 16
npx wrangler deploy
```

Then add a route or custom domain (for example `try.tryvinci.com`) in the Cloudflare dashboard.

## Test

```bash
npm test         # quota, safety, error and page tests with a fake AI binding
npm run typecheck
```
