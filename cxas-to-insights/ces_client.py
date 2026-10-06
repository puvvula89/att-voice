"""Minimal REST client for the CES and Insights APIs.

Deliberately dependency-light: an access token from the gcloud CLI plus urllib.
That keeps the runbook in README.md reproducible on any machine with gcloud and
Python 3, with no SDK version pinning to get wrong.
"""
import json
import os
import subprocess
import time
import urllib.error
import urllib.request

_ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")

try:
    from dotenv import load_dotenv

    load_dotenv(_ENV_PATH)
except ImportError:
    # Keep this runnable on a bare machine: python-dotenv is a convenience, not
    # a requirement. Existing environment variables always win.
    if os.path.exists(_ENV_PATH):
        with open(_ENV_PATH) as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip().strip("'\""))

PROJECT = os.environ.get("CXAS_PROJECT") or os.environ["GOOGLE_CLOUD_PROJECT"]
LOCATION = os.environ.get("CXAS_LOCATION", "us")
INSIGHTS_LOCATION = os.environ.get("INSIGHTS_LOCATION", "us")
APP_ID = os.environ.get("APP_ID", "insights-demo")
AGENT_ID = os.environ.get("AGENT_ID", "concierge")
APP_MODEL = os.environ.get("APP_MODEL", "gemini-3.5-flash")

CES_ROOT = f"https://ces.googleapis.com/v1beta/projects/{PROJECT}/locations/{LOCATION}"
APP = f"projects/{PROJECT}/locations/{LOCATION}/apps/{APP_ID}"

# Insights requires a REGIONAL ENDPOINT whose prefix matches the location in the
# path. Calling the global host for a non-global location fails with
# "Location Mismatch: Server location `global` and resource location `us` do not
# match". `global` is the only location served by the unprefixed host.
INSIGHTS_HOST = (
    "contactcenterinsights.googleapis.com"
    if INSIGHTS_LOCATION == "global"
    else f"{INSIGHTS_LOCATION}-contactcenterinsights.googleapis.com"
)
INSIGHTS_ROOT = (
    f"https://{INSIGHTS_HOST}/v1/projects/{PROJECT}/locations/{INSIGHTS_LOCATION}"
)


def token():
    return subprocess.run(
        ["gcloud", "auth", "print-access-token"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


def call(method, url, body=None):
    """One REST call. Returns parsed JSON, or {'__err': code, '__body': text}."""
    headers = {
        "Authorization": f"Bearer {token()}",
        "Content-Type": "application/json",
        # Billing/quota project, required when the resource project differs from
        # the gcloud default project.
        "x-goog-user-project": PROJECT,
    }
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, headers=headers, method=method, data=data)
    try:
        return json.loads(urllib.request.urlopen(req, timeout=180).read().decode() or "{}")
    except urllib.error.HTTPError as e:
        return {"__err": e.code, "__body": e.read().decode()[:600]}


def wait_lro(resp, label, attempts=120, delay=5):
    """Block on a CES long-running operation. Returns True on success.

    CES returns an LRO for app, agent, version and deployment creation. These
    routinely take several minutes: in a cold-start run, agent/version/deployment
    each exceeded 200s while still succeeding. Hence the generous budget (10 min).

    A timeout here means "unknown", NOT "failed" — the resource usually lands
    shortly afterwards. Callers re-read the resource to decide.
    """
    op = resp.get("name")
    if not op:
        print(f"  {label}: {json.dumps(resp)[:400]}")
        return False
    for _ in range(attempts):
        time.sleep(delay)
        done = call("GET", f"https://ces.googleapis.com/v1beta/{op}")
        if done.get("done"):
            err = done.get("error")
            print(f"  {label}: {'FAILED ' + json.dumps(err)[:300] if err else 'ok'}")
            return not err
    print(f"  {label}: still running after {attempts * delay}s — re-read the resource")
    return False
