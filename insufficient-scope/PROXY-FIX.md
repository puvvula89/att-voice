# Fix: `ACCESS_TOKEN_SCOPE_INSUFFICIENT` behind a corporate proxy

## Symptom

`CreateSession` fails inside the Agent Engine container with:

```
403 PERMISSION_DENIED   reason = ACCESS_TOKEN_SCOPE_INSUFFICIENT
"Request had insufficient authentication scopes."
```

…even though the runtime service account has `aiplatform.admin` / `aiplatform.user`.

## Cause

The deploy sets `HTTP_PROXY` / `HTTPS_PROXY` but **no `NO_PROXY`**. Every outbound
call is therefore forced through the corporate proxy — including the calls that
mint the runtime token (the metadata server and the `oauth2` / `sts` /
`iamcredentials` token exchange). The TLS-intercepting proxy re-issues those
connections and the token comes back **without the `cloud-platform` scope**.
`CreateSession` checks scope before roles, sees `cloud-platform` missing, and
returns 403. It is a **scope** problem created in transit, not an IAM problem.

## Fix — add `NO_PROXY` to the deploy `env_vars`

In `deploy/deploy_agent_engine.py`, **immediately after** the existing proxy
lines, add the `NO_PROXY` entries:

```python
ENV_VARS["HTTPS_PROXY"] = "http://optimus-proxy.dev.att.internal:8888"
ENV_VARS["HTTP_PROXY"]  = "http://optimus-proxy.dev.att.internal:8888"

# Google auth + APIs MUST bypass the corporate proxy:
#  - the metadata server (token source) is link-local; proxying it breaks auth.
#  - *.googleapis.com (oauth2 / sts / iamcredentials / aiplatform) must go direct
#    so the token exchange is not intercepted (interception strips cloud-platform).
_NO_PROXY = "metadata.google.internal,169.254.169.254,.googleapis.com,.google.internal,localhost,127.0.0.1"
ENV_VARS["NO_PROXY"] = _NO_PROXY
ENV_VARS["no_proxy"] = _NO_PROXY   # set both cases — libraries read different names
```

Nothing else changes. The corporate proxy still handles internal traffic
(`att.com`, `dev.att.internal`, `sbc.com`, …); `NO_PROXY` only carves out
Google's auth and API endpoints so the runtime token keeps its full
`cloud-platform` scope.

## Required IAM (custom service-account engines)

A `SERVICE_ACCOUNT` engine has the reasoning-engine service agent impersonate the
runtime SA, so that agent needs token-creator on it (one-time):

```bash
PROJECT=att-ccai-optimus-dev
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')
gcloud iam service-accounts add-iam-policy-binding \
  vertex-ai-auth@$PROJECT.iam.gserviceaccount.com \
  --member="serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-aiplatform-re.iam.gserviceaccount.com" \
  --role="roles/iam.serviceAccountTokenCreator"
```

## Redeploy and verify

A running container keeps its old env, so redeploy after the change:

```bash
python deploy/deploy_agent_engine.py
```

The runtime token should then carry `cloud-platform` and `CreateSession` returns
200 — with the custom service account, proxy, and PSC config all unchanged.

## Note if Google APIs are only reachable through the proxy

The fix above assumes `*.googleapis.com` is reachable **directly** from the
container (Private Google Access / restricted VIP — consistent with a PSC +
DNS-peering setup). If the container's only egress to Google is through the
proxy, do **not** add `googleapis.com` to `NO_PROXY`; instead configure the proxy
to **not TLS-intercept** `*.googleapis.com` and the metadata host. The
`metadata.google.internal` / `169.254.169.254` exclusion is required either way.
