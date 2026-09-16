# Google Health → Claude (remote MCP server, free hosting)

Lets Claude read your **Fitbit Air** metrics live, from **claude.ai on the web**,
via the **Google Health API** (the successor to the retired Fitbit Web API).
The server runs as a public HTTPS endpoint you add to Claude as a custom
connector. These steps host it **free** on Google Cloud Run.

    Fitbit Air ──BLE──▶ Google Health app (phone) ──sync──▶ Google Health API ──▶ this server ──▶ Claude (web)

The Air only talks to the phone app, and the app syncs roughly every 15 minutes,
so "live" means *as fresh as your last phone sync* — not this instant.

## Files

| File | Purpose |
|------|---------|
| `google_health_mcp.py` | the MCP server (Streamable HTTP, stateless, headless auth) |
| `get_refresh_token.py`  | run once locally to mint your Google refresh token |
| `requirements.txt`      | dependencies |
| `Dockerfile`            | container image for Cloud Run |
| `.dockerignore`         | keeps secrets/cruft out of the image |

---

## Step 1 — Google Cloud project + OAuth client

Exact steps (they change): https://developers.google.com/health/setup and
https://developers.google.com/health/developer-checklist

1. In the Google Cloud console, create a project and **enable the Google Health API**.
2. **OAuth consent screen** → User type **External**, publishing status
   **Testing**. Add the Google account your Air is on as a **Test user**. Add the
   read-only Health scopes.
3. **Credentials → Create OAuth client ID → Application type: Desktop app.**
   Download the JSON as `client_secret.json` into this folder.

## Step 2 — Confirm three API strings

Open `google_health_mcp.py`, CONFIG block:
- `API_BASE` — host + version, from the REST reference.
- `SCOPES` — exact scope strings, from https://developers.google.com/health/scopes
  (also update the copy in `get_refresh_token.py` to match).
- `PARAM_START` / `PARAM_END` — time-filter param names, from the Filters/Endpoints pages.

Shortcut: feed Google's parity-tool context file
(https://developers.google.com/health/migration/parity-tool) to Claude and ask
it to fill the exact strings.

## Step 3 — Mint your refresh token (once, locally)

    python3 -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt
    python get_refresh_token.py

A browser opens; approve. It prints three lines:

    GOOGLE_CLIENT_ID=...
    GOOGLE_CLIENT_SECRET=...
    GOOGLE_REFRESH_TOKEN=...

Keep them secret — you'll paste them into Cloud Run next.

## Step 4 — Deploy free to Google Cloud Run

Prereqs: install the gcloud CLI, then `gcloud auth login` and
`gcloud config set project YOUR_PROJECT_ID`.

From this folder:

    gcloud run deploy google-health-mcp \
      --source . \
      --region europe-west1 \
      --allow-unauthenticated \
      --set-env-vars "GOOGLE_CLIENT_ID=xxx,GOOGLE_CLIENT_SECRET=yyy,GOOGLE_REFRESH_TOKEN=zzz"

- Approve the prompts to enable Cloud Build / Artifact Registry the first time.
- If any secret value contains a comma, switch the delimiter:
  `--set-env-vars "^@^GOOGLE_CLIENT_ID=xxx@GOOGLE_CLIENT_SECRET=yyy@GOOGLE_REFRESH_TOKEN=zzz"`
  (or store them in Secret Manager and use `--set-secrets`).
- Cloud Run's free tier (≈2M requests/month, scale-to-zero) easily covers
  personal use — idle costs nothing.

It prints a **Service URL** like `https://google-health-mcp-xxxx.europe-west1.run.app`.
Your connector URL is that **+ `/mcp`**.

Quick sanity check (should return HTTP 400/406, i.e. it's alive and speaking MCP):

    curl -i https://YOUR-SERVICE-URL/mcp

## Step 5 — Add it to claude.ai (web)

**Settings → Connectors → Add custom connector** → paste `https://YOUR-SERVICE-URL/mcp`.
On Team/Enterprise accounts only an org owner can add connectors; on personal
Pro/Max it's self-serve.

## Step 6 — Test in a chat immediately

Ask: *"Using the google-health tools, what was my resting heart rate over the
last two weeks?"* Watch whether Claude actually calls a tool.

---

## Caveats (read these)

- **claude.ai web may connect but not use the tools.** Through 2026 there have
  been repeated reports where a custom remote connector shows *Connected* with
  its tools listed in Settings, yet the model never gets them in chat (or only
  offers to use them inside an artifact). The same servers work in Claude Code
  and via the API. If Step 6 fails that way, it's a platform issue, not your
  server — the reliable custom-MCP surfaces today are **Claude Code** and the
  **Messages API**.
- **The endpoint is public.** claude.ai's connector supports authless or OAuth —
  there's no static-token field — so this server is reachable by anyone with the
  URL. Mitigations here: all tools are **read-only**, and the URL is
  unguessable. If that's not enough for health data, the real fix is putting
  OAuth in front (heavier), or not using the web surface.
- **~weekly re-consent.** In OAuth Testing mode the refresh token expires about
  every 7 days. When calls start failing auth, re-run `get_refresh_token.py` and
  update `GOOGLE_REFRESH_TOKEN` (`gcloud run services update google-health-mcp
  --update-env-vars GOOGLE_REFRESH_TOKEN=new`). Publishing to Production avoids
  this but triggers Google's full verification + likely a security assessment —
  not worth it for a personal tool.

## Alternative free host (no deploy)

Run the server locally and expose it with a **Cloudflare Tunnel** (`cloudflared
tunnel --url http://localhost:8080`) or ngrok — you get a public HTTPS URL while
your machine is on. Same connector steps, but your laptop has to be running.

## Tools

| Tool | Returns |
|------|---------|
| `get_daily_activity(days)`     | steps, distance, active minutes, total calories per day |
| `get_sleep(days)`              | sleep sessions (stages, duration, efficiency) |
| `get_resting_heart_rate(days)` | daily resting HR |
| `get_hrv(days)`                | daily heart-rate variability |
| `get_workouts(days)`           | logged exercise sessions |
| `get_data_points(type, days)`  | raw points for any data type (escape hatch) |
