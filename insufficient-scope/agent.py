"""Scope probe agent for Vertex AI Agent Engine.

A minimal Agent Engine app whose only job is to report, from *inside* the
deployed container, which credential the runtime actually uses and whether that
credential's token can create a session. Use it to diagnose a
``CreateSession`` failure of the form::

    403 PERMISSION_DENIED  reason=ACCESS_TOKEN_SCOPE_INSUFFICIENT
    "Request had insufficient authentication scopes."

Deploy it with the SAME project, region, and runtime service account your real
agent uses, then compare the printed output against the healthy reference in the
README. The field that differs points at the cause.

The single queryable method is ``query`` (Agent Engine exposes it automatically;
no operation registration required).
"""


class ScopeProbe:
    def set_up(self) -> None:
        pass

    def query(self, **kwargs):
        import os
        import google.auth
        from google.auth.transport.requests import Request, AuthorizedSession

        out = {}

        # 1) Which credential does Application Default Credentials resolve to in
        #    this container? A healthy runtime resolves to the metadata server
        #    (compute_engine.Credentials). A file or a federated/impersonated
        #    config resolving here is the usual cause of a narrowed token.
        creds, project = google.auth.default()
        out["cred_class"] = f"{type(creds).__module__}.{type(creds).__name__}"
        out["adc_project"] = project
        out["has_impersonation"] = (
            hasattr(creds, "_impersonated_credentials")
            or "impersonat" in type(creds).__name__.lower()
            or "external_account" in type(creds).__module__
        )
        out["GOOGLE_APPLICATION_CREDENTIALS"] = os.environ.get(
            "GOOGLE_APPLICATION_CREDENTIALS", "(unset)"
        )

        # 2) What identity and OAuth scopes does the runtime token actually carry?
        #    The token MUST include .../auth/cloud-platform for aiplatform calls.
        try:
            creds.refresh(Request())
            import requests

            info = requests.get(
                "https://oauth2.googleapis.com/tokeninfo",
                params={"access_token": creds.token},
                timeout=15,
            ).json()
            out["token_email"] = info.get("email")
            out["token_scope"] = info.get("scope")
            out["has_cloud_platform"] = (
                "https://www.googleapis.com/auth/cloud-platform"
                in (info.get("scope") or "")
            )
        except Exception as e:
            out["tokeninfo_error"] = f"{type(e).__name__}: {str(e)[:200]}"

        # 3) The exact failing call, made from inside the container against this
        #    engine's own session store. Mirrors what the real agent does.
        try:
            engine_id = os.environ.get("GOOGLE_CLOUD_AGENT_ENGINE_ID", "")
            location = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
            url = (
                f"https://{location}-aiplatform.googleapis.com/v1beta1/"
                f"projects/{project}/locations/{location}/"
                f"reasoningEngines/{engine_id}/sessions"
            )
            resp = AuthorizedSession(creds).post(url, json={"userId": "scope-probe"})
            out["create_session_http"] = resp.status_code
            body = resp.json()
            if "error" in body:
                err = body["error"]
                details = err.get("details", [{}])
                out["create_session_status"] = err.get("status")
                out["create_session_reason"] = details[0].get("reason") if details else None
                out["create_session_message"] = err.get("message")
            else:
                out["create_session_status"] = "OK"
        except Exception as e:
            out["create_session_error"] = f"{type(e).__name__}: {str(e)[:200]}"

        return out


# Module-level instance is what gets deployed.
probe = ScopeProbe()
