"""Turn on public widget access for a deployment so chat tokens can be minted.

GenerateChatToken fails with FailedPrecondition ("Public access is not enabled for
the deployment") until this is set. That is a finding in its own right: minting a
session-scoped token is gated on a per-DEPLOYMENT widget security flag, not just on
IAM. Whoever owns the deployment controls whether direct-connect is possible at all.

The same message names the alternative: with public access off, "the web widget must
be integrated with your own authentication and authorization system to return valid
credentials". So this flag is the vendor's public/private switch, and the private side
is the one an enterprise would actually ship.

Scoped deliberately for the spike:
    enable_public_access = True    required to mint a token
    enable_origin_check  = False   the harness is not a browser, so it sends no Origin
    modality             = CHAT_AND_VOICE   we are testing audio, not just chat

Usage:
    python bootstrap/enable_public_access.py [DEPLOYMENT_ID]
"""

import os
import sys

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), os.pardir, ".env"))

import google.cloud.ces_v1beta as ces
from google.api_core.client_options import ClientOptions
from google.protobuf import field_mask_pb2

PROJECT = os.environ.get("CXAS_PROJECT") or os.environ["GOOGLE_CLOUD_PROJECT"]
LOCATION = os.environ.get("CXAS_LOCATION", "us")
APP_ID = os.environ.get("VOICE_APP_ID", "ivr-and-app-voice")
APP = f"projects/{PROJECT}/locations/{LOCATION}/apps/{APP_ID}"

DEPLOYMENT_ID = (sys.argv[1] if len(sys.argv) > 1 else "spike").strip()
DEPLOYMENT = f"{APP}/deployments/{DEPLOYMENT_ID}"

WidgetConfig = ces.ChannelProfile.WebWidgetConfig


def main():
    client = ces.AgentServiceClient(
        client_options=ClientOptions(api_endpoint="ces.googleapis.com")
    )
    current = client.get_deployment(request=ces.GetDeploymentRequest(name=DEPLOYMENT))
    print(f"deployment={DEPLOYMENT}")
    print("  before:", current.channel_profile.web_widget_config.security_settings or "<unset>")

    deployment = ces.Deployment(
        name=DEPLOYMENT,
        channel_profile=ces.ChannelProfile(
            web_widget_config=WidgetConfig(
                modality=WidgetConfig.Modality.CHAT_AND_VOICE,
                security_settings=WidgetConfig.SecuritySettings(
                    enable_public_access=True,
                    enable_origin_check=False,
                ),
            )
        ),
    )
    updated = client.update_deployment(
        request=ces.UpdateDeploymentRequest(
            deployment=deployment,
            update_mask=field_mask_pb2.FieldMask(paths=["channel_profile"]),
        )
    )
    print("  after :", updated.channel_profile.web_widget_config.security_settings)
    print("\nPublic access enabled. Remember to delete this deployment when the spike ends.")


if __name__ == "__main__":
    main()
