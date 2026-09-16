#!/usr/bin/env python3
"""
Run ONCE, locally, to mint a Google refresh token for the server.

Prereq: client_secret.json (your Desktop OAuth client) in this folder.
It opens a browser, you approve, and it prints the three values to set as
environment variables / secrets on your host.

    pip install google-auth-oauthlib
    python get_refresh_token.py
"""
from google_auth_oauthlib.flow import InstalledAppFlow

# MUST match SCOPES in google_health_mcp.py exactly.
SCOPES = [
    "https://www.googleapis.com/auth/googlehealth.activity_and_fitness.readonly",
    "https://www.googleapis.com/auth/googlehealth.health_metrics_and_measurements.readonly",
    "https://www.googleapis.com/auth/googlehealth.sleep.readonly",
    "https://www.googleapis.com/auth/googlehealth.nutrition.readonly",
]


def main() -> None:
    flow = InstalledAppFlow.from_client_secrets_file("client_secret.json", SCOPES)
    # access_type=offline + prompt=consent guarantee a refresh token comes back.
    creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")

    print("\n=== set these on your host (keep them secret) ===")
    print(f"GOOGLE_CLIENT_ID={creds.client_id}")
    print(f"GOOGLE_CLIENT_SECRET={creds.client_secret}")
    print(f"GOOGLE_REFRESH_TOKEN={creds.refresh_token}")


if __name__ == "__main__":
    main()