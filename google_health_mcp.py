#!/usr/bin/env python3
"""
Google Health API -> MCP server (remote / claude.ai web edition).

Exposes your Fitbit Air metrics -- via the Google Health API, the successor to
the retired Fitbit Web API -- to Claude as MCP tools, over a public HTTPS
endpoint that claude.ai can reach as a custom connector.

  Transport : Streamable HTTP (stateless), served at /mcp
  Auth      : Google OAuth 2.0, HEADLESS. The server holds a long-lived refresh
              token (an env var) and mints access tokens itself -- no browser on
              the server. Mint the refresh token once with get_refresh_token.py.

Environment variables the server needs (set on your host):
  GOOGLE_CLIENT_ID       from your Desktop OAuth client
  GOOGLE_CLIENT_SECRET   from your Desktop OAuth client
  GOOGLE_REFRESH_TOKEN   printed by get_refresh_token.py
  PORT                   injected by the host (Cloud Run sets 8080)

Confirm before first run (all isolated in CONFIG, override via env):
  1. API_BASE  -> https://developers.google.com/health/reference/rest
  2. SCOPES    -> https://developers.google.com/health/scopes
  3. PARAM_*   -> https://developers.google.com/health/filters  +  .../endpoints
Google ships an LLM-ready context file to fill these exactly:
  https://developers.google.com/health/migration/parity-tool
"""
from __future__ import annotations

import datetime as dt
import json
import os
import time
from typing import Any

import httpx
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from mcp.server.fastmcp import FastMCP

# ─────────────────────────── CONFIG (confirm these) ──────────────────────────
API_BASE = os.environ.get("HEALTH_API_BASE", "https://health.googleapis.com/v4")

_SCOPE_PREFIX = "https://www.googleapis.com/auth/googlehealth"
SCOPES = [
    f"{_SCOPE_PREFIX}.activity_and_fitness.readonly",
    f"{_SCOPE_PREFIX}.health_metrics_and_measurements.readonly",
    f"{_SCOPE_PREFIX}.sleep.readonly",
    f"{_SCOPE_PREFIX}.nutrition.readonly",
]

PARAM_START = os.environ.get("HEALTH_PARAM_START", "startTime")
PARAM_END = os.environ.get("HEALTH_PARAM_END", "endTime")

# API caps aggregation ranges: 14 days for these, 90 for everything else.
SHORT_WINDOW_TYPES = {
    "heart-rate", "active-minutes", "total-calories", "calories-in-heart-rate-zone",
}
# Response envelope key varies by endpoint; grab the first list-shaped field.
LIST_KEYS = ("dataPoints", "dailyRollupDataPoints", "rollupDataPoints", "sessions")
# ──────────────────────────────────────────────────────────────────────────────

# stateless_http + json_response => robust on scale-to-zero / multi-instance
# hosts like Cloud Run (no server-side session to lose on a cold start).
mcp = FastMCP(
    "google-health",
    stateless_http=True,
    json_response=True,
    host="0.0.0.0",                               # bind all interfaces (Cloud Run)
    port=int(os.environ.get("PORT", "8080")),     # Cloud Run injects PORT
)


# ── Google auth (headless, refresh-token only) ────────────────────────────────
_CREDS: Credentials | None = None


def _credentials() -> Credentials:
    global _CREDS
    if _CREDS is None:
        _CREDS = Credentials(
            token=None,
            refresh_token=os.environ["GOOGLE_REFRESH_TOKEN"],
            token_uri="https://oauth2.googleapis.com/token",
            client_id=os.environ["GOOGLE_CLIENT_ID"],
            client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
            scopes=SCOPES,
        )
    if not _CREDS.valid:
        # Raises if the refresh token was revoked/expired. In OAuth "testing" mode
        # these last ~7 days -> re-run get_refresh_token.py and update the env var.
        _CREDS.refresh(Request())
    return _CREDS


def _client() -> httpx.Client:
    return httpx.Client(
        base_url=API_BASE,
        headers={"Authorization": f"Bearer {_credentials().token}"},
        timeout=30.0,
    )


# ── HTTP: pagination + exponential backoff ────────────────────────────────────
def _extract(body: dict) -> tuple[list, str | None]:
    for key in LIST_KEYS:
        if key in body:
            return body[key], body.get("nextPageToken")
    return [body], body.get("nextPageToken")  # unknown shape -> surface it


def _get(path: str, params: dict[str, Any]) -> list[dict]:
    out: list[dict] = []
    params = dict(params)
    with _client() as client:
        while True:
            for attempt in range(5):
                resp = client.get(path, params=params)
                if resp.status_code in (429, 504):
                    time.sleep(2 ** attempt)
                    continue
                resp.raise_for_status()
                break
            else:
                raise RuntimeError(f"Persistent rate limiting on {path}")
            items, next_token = _extract(resp.json())
            out.extend(items)
            if not next_token:
                return out
            params["pageToken"] = next_token


# ── time helpers ──────────────────────────────────────────────────────────────
def _rfc3339(t: dt.datetime) -> str:
    return t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _window(days: int) -> dict[str, str]:
    end = dt.datetime.now(dt.timezone.utc)
    return {PARAM_START: _rfc3339(end - dt.timedelta(days=days)), PARAM_END: _rfc3339(end)}


def _points(data_type: str, days: int) -> list[dict]:
    if data_type in SHORT_WINDOW_TYPES:
        days = min(days, 14)
    return _get(f"/users/me/dataTypes/{data_type}/dataPoints", _window(days))


# ── MCP tools ─────────────────────────────────────────────────────────────────
# Fitbit Air data types (full list: /health/data-types):
#   steps · distance · active-minutes · active-zone-minutes · total-calories
#   active-energy-burned · heart-rate · daily-resting-heart-rate
#   daily-heart-rate-variability · oxygen-saturation · daily-oxygen-saturation
#   daily-respiratory-rate · vo2-max · sleep · exercise · sedentary-period

@mcp.tool()
def get_data_points(data_type: str, days: int = 7) -> str:
    """Raw data points for any Google Health data type over the last N days.
    data_type uses hyphens, e.g. 'heart-rate', 'sleep', 'daily-resting-heart-rate'."""
    return json.dumps(_points(data_type, days), indent=2)


@mcp.tool()
def get_daily_activity(days: int = 7) -> str:
    """Steps, distance, active minutes and total calories per day, last N days."""
    return json.dumps(
        {name: _points(name, days)
         for name in ("steps", "distance", "active-minutes", "total-calories")},
        indent=2,
    )


@mcp.tool()
def get_sleep(days: int = 7) -> str:
    """Recent sleep sessions (stages, duration, efficiency), last N days."""
    return json.dumps(_points("sleep", days), indent=2)


@mcp.tool()
def get_resting_heart_rate(days: int = 14) -> str:
    """Daily resting heart rate, last N days."""
    return json.dumps(_points("daily-resting-heart-rate", days), indent=2)


@mcp.tool()
def get_hrv(days: int = 14) -> str:
    """Daily heart-rate variability, last N days."""
    return json.dumps(_points("daily-heart-rate-variability", days), indent=2)


@mcp.tool()
def get_workouts(days: int = 14) -> str:
    """Logged exercise / workout sessions, last N days."""
    return json.dumps(_points("exercise", days), indent=2)


if __name__ == "__main__":
    mcp.run(transport="streamable-http")