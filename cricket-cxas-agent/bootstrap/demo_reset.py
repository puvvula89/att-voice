"""Reseed the demo account on the deployed support server.

    .venv/bin/python bootstrap/demo_reset.py P1      # suspended line
    .venv/bin/python bootstrap/demo_reset.py P2      # outage at the caller's zip
    .venv/bin/python bootstrap/demo_reset.py P3      # clean account (default)

Profiles are PRD §7. The call is authenticated with the caller's own identity
token; the service is private, so this works for anyone with run.invoker.
"""
import json
import os
import subprocess
import sys
import urllib.request

from common import PROJECT

REGION = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
SERVICE = os.environ.get("SUPPORT_MCP_SERVICE", "cricket-support-mcp")


def service_url() -> str:
    return subprocess.check_output(
        ["gcloud", "run", "services", "describe", SERVICE, "--region", REGION, "--project", PROJECT,
         "--format=value(status.url)"], text=True).strip()


def reset(profile: str) -> dict:
    url = f"{service_url()}/admin/reset?profile={profile}"
    token = subprocess.check_output(["gcloud", "auth", "print-identity-token"], text=True).strip()
    req = urllib.request.Request(url, method="POST", headers={"authorization": f"Bearer {token}"})
    try:
        return json.load(urllib.request.urlopen(req, timeout=20))
    except urllib.error.HTTPError as e:
        sys.exit(f"reset failed: {e.code} {e.read().decode()[:200]}")


def main():
    print(json.dumps(reset(sys.argv[1] if len(sys.argv) > 1 else "P3")))


if __name__ == "__main__":
    main()
