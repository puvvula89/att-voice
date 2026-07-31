"""Publish a deployment of the app.

GenerateChatToken REQUIRES a `deployment` -- a token cannot be minted against the
draft. That makes a published deployment a hard prerequisite for any direct-connect
design, and it is the same class of gotcha as GTP version pinning: what the draft
does and what a deployment does can differ.

Creating a deployment first snapshots the draft as an app version, then publishes
that version. Both calls return the created resource directly.

Usage:
    python bootstrap/create_deployment.py [DEPLOYMENT_ID]
"""

import os
import sys

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), os.pardir, ".env"))

import google.cloud.ces_v1beta as ces
from google.api_core.client_options import ClientOptions

PROJECT = os.environ.get("CXAS_PROJECT") or os.environ["GOOGLE_CLOUD_PROJECT"]
LOCATION = os.environ.get("CXAS_LOCATION", "us")
APP_ID = os.environ.get("VOICE_APP_ID", "ivr-and-app-voice")
APP = f"projects/{PROJECT}/locations/{LOCATION}/apps/{APP_ID}"

DEPLOYMENT_ID = (sys.argv[1] if len(sys.argv) > 1 else "spike").strip()


def main():
    client = ces.AgentServiceClient(
        client_options=ClientOptions(api_endpoint="ces.googleapis.com")
    )
    print(f"app={APP}")

    print("\n[1] Snapshot the draft as an app version")
    version = client.create_app_version(
        request=ces.CreateAppVersionRequest(
            parent=APP,
            app_version=ces.AppVersion(display_name=f"{DEPLOYMENT_ID} snapshot"),
        )
    )
    print("   ->", version.name)

    print(f"\n[2] Publish deployment '{DEPLOYMENT_ID}'")
    deployment = client.create_deployment(
        request=ces.CreateDeploymentRequest(
            parent=APP,
            deployment_id=DEPLOYMENT_ID,
            deployment=ces.Deployment(
                display_name=DEPLOYMENT_ID,
                app_version=version.name,
            ),
        )
    )
    print("   ->", deployment.name)
    print(f"\nSPIKE_DEPLOYMENT_ID={DEPLOYMENT_ID}")


if __name__ == "__main__":
    main()
