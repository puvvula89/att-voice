"""Create the CXAS app and the `sales-adapter` OpenAPI toolset from scratch.

This is the FIRST CXAS step in a clean-slate deploy (before create_steering_tree.py
and apply_sales_callbacks.py):
  1. create the app `att-ivr-steering` (idempotent — tolerates ALREADY_EXISTS)
  2. create the `sales-adapter` OpenAPI toolset pointing at the adapter service,
     authenticated with the CES service-agent OIDC ID token.

The OpenAPI schema mirrors the adapter's POST /cxas/turn contract (operation
`call_sales_specialist`). For an existing app whose toolset just needs a new URL,
use repoint_toolset.py instead.

Usage: python create_cxas_app.py <ADAPTER_BASE_URL>
Config from env: CXAS_PROJECT, CXAS_LOCATION, CXAS_APP_ID.
"""
import json
import os
import sys

import google.cloud.ces_v1beta.types as T
from cxas_scrapi.core.apps import Apps
from cxas_scrapi.core.agents import Agents

PROJECT = os.environ.get("CXAS_PROJECT") or os.environ["GOOGLE_CLOUD_PROJECT"]
LOCATION = os.environ.get("CXAS_LOCATION", "us")
APP_ID = os.environ.get("CXAS_APP_ID", "att-ivr-steering")
APP = f"projects/{PROJECT}/locations/{LOCATION}/apps/{APP_ID}"
TOOLSET_ID = "sales-adapter"
TOOLSET = f"{APP}/toolsets/{TOOLSET_ID}"

# OpenAPI contract for the adapter's POST /cxas/turn (operation call_sales_specialist).
# servers[0].url is filled in from the ADAPTER_BASE_URL argument at run time.
SCHEMA = {
    "openapi": "3.0.0",
    "info": {"title": "Sales Specialist Adapter", "version": "1.0.0"},
    "servers": [{"url": "REPLACED_AT_RUNTIME"}],
    "paths": {
        "/cxas/turn": {
            "post": {
                "operationId": "call_sales_specialist",
                "summary": "Reach the AT&T sales specialist for ANY device upgrade, phone, plan, line, trade-in, price, or order request.",
                "description": (
                    "REQUIRED for every device or sales turn. The Telephony Sales Master is only a "
                    "router and has NO product knowledge of its own — the specialist reached through "
                    "this tool owns the phone catalog, pricing, eligibility, trade-in values, and order "
                    "placement. Call this tool on EVERY turn where the caller talks about a device, "
                    "upgrade, phone, plan, line, trade-in, price, or placing/confirming an order — "
                    "including the very first thing they say after being routed here. Pass the caller's "
                    "exact words as `utterance` and the session `customer_id`, then speak the returned "
                    "`response_text` verbatim. Never answer these from your own knowledge and never "
                    "invent lines, prices, eligibility, or confirmations. Only skip this tool for a "
                    "pure greeting or when the caller is finished and you are closing the call."
                ),
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "customer_id": {"type": "string"},
                                    "utterance": {"type": "string"},
                                    "session_id": {"type": "string"},
                                    "caller_sentiment_label": {
                                        "type": "string",
                                        "enum": ["calm", "neutral", "annoyed", "frustrated", "angry"],
                                        "description": "Your read of the caller's emotional tone on THIS turn.",
                                    },
                                    "caller_sentiment_score": {
                                        "type": "number",
                                        "description": "Frustration intensity from 0.0 (calm) to 1.0 (furious).",
                                    },
                                },
                                "required": ["customer_id", "utterance"],
                            }
                        }
                    },
                },
                "responses": {
                    "200": {
                        "description": "reply",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "response_text": {"type": "string"},
                                        "session_id": {"type": "string"},
                                    },
                                }
                            }
                        },
                    }
                },
            }
        }
    },
}


def _tolerate_exists(fn, *a, **k):
    try:
        return fn(*a, **k)
    except Exception as e:
        msg = str(e).lower()
        if "exist" in msg or "already_exists" in msg:
            print(f"  (already exists) {type(e).__name__}")
            return None
        raise


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: create_cxas_app.py <ADAPTER_BASE_URL>")
    base = sys.argv[1].rstrip("/")
    print(f"project={PROJECT} location={LOCATION}\napp={APP}\nadapter={base}")

    # 1) App.
    print("\n[1] App att-ivr-steering")
    apps = Apps(project_id=PROJECT, location=LOCATION)
    _tolerate_exists(apps.create_app, app_id=APP_ID, display_name="AT&T IVR Steering")

    # 2) sales-adapter OpenAPI toolset (URL + OIDC). If one already exists, delete
    #    it first so this is repeatable (create_toolset has no upsert).
    print("\n[2] Toolset sales-adapter (OpenAPI + OIDC)")
    client = Agents(app_name=APP).client
    try:
        client.delete_toolset(request=T.DeleteToolsetRequest(name=TOOLSET, force=True))
        print("   (removed pre-existing toolset)")
    except Exception:
        pass

    schema = dict(SCHEMA)
    schema["servers"] = [{"url": base}]
    toolset = T.Toolset(
        display_name="sales_adapter",
        open_api_toolset=T.OpenApiToolset(
            open_api_schema=json.dumps(schema),
            api_authentication=T.ApiAuthentication(
                service_agent_id_token_auth_config=T.ServiceAgentIdTokenAuthConfig()
            ),
        ),
    )
    created = client.create_toolset(
        request=T.CreateToolsetRequest(parent=APP, toolset_id=TOOLSET_ID, toolset=toolset)
    )
    print("   created:", created.name, "(op call_sales_specialist -> %s/cxas/turn, OIDC)" % base)


if __name__ == "__main__":
    main()
