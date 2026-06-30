# Scope Probe — diagnose `ACCESS_TOKEN_SCOPE_INSUFFICIENT` on Agent Engine

A tiny, self-contained Agent Engine app that reports — from **inside the deployed
container** — which credential the runtime actually uses and whether that
credential can create a session. Deploy it with the **same project, region, and
runtime service account** as your real agent, read the printed JSON, and compare
it against the healthy reference below. The field that differs is the cause.

Use this when `CreateSession` fails with:

```
403 PERMISSION_DENIED   reason = ACCESS_TOKEN_SCOPE_INSUFFICIENT
"Request had insufficient authentication scopes."
```

That error is about the **OAuth scope of the runtime token**, not IAM roles. A
service account can hold `aiplatform.admin`/`aiplatform.user` and still be
rejected if its token is minted without `cloud-platform`. This probe shows you
exactly what the container's token looks like.

---

## Prerequisites

- **Python 3.12** on the deploy host. The Agent Engine container runs 3.12; the
  agent is pickled here and unpickled in the container, so a mismatched Python
  version produces a container that fails to start.
- Authenticated gcloud / Application Default Credentials with permission to
  deploy Agent Engine in the target project.
- A GCS staging bucket (defaults to `<project>-agent-engine`).

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## If you run the engine as a custom service account

To reproduce your real setup, deploy the probe **as your agent's runtime service
account** (`RUNTIME_SERVICE_ACCOUNT`, below). Agent Engine impersonates that SA
via the reasoning-engine service agent, so two bindings are required:

```bash
PROJECT=your-project
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')
SA=your-runtime-sa@your-project.iam.gserviceaccount.com

# 1) the reasoning-engine service agent must be able to mint tokens for your SA
gcloud iam service-accounts add-iam-policy-binding "$SA" \
  --member="serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-aiplatform-re.iam.gserviceaccount.com" \
  --role="roles/iam.serviceAccountTokenCreator"

# 2) the deploying principal must be allowed to run the engine as your SA
gcloud iam service-accounts add-iam-policy-binding "$SA" \
  --member="user:you@example.com" \
  --role="roles/iam.serviceAccountUser"
```

(Skip this section entirely to test the default managed identity instead.)

---

## Run it

```bash
# Custom SA (matches your real agent — recommended):
GOOGLE_CLOUD_PROJECT=your-project \
GOOGLE_CLOUD_LOCATION=us-central1 \
RUNTIME_SERVICE_ACCOUNT=your-runtime-sa@your-project.iam.gserviceaccount.com \
python deploy.py

# Or the default managed identity (baseline):
GOOGLE_CLOUD_PROJECT=your-project python deploy.py
```

The script builds the engine, runs the probe in-container, prints the JSON, and
**tears the engine down**. Set `KEEP_ENGINE=1` to leave it deployed (then delete
it later with `python destroy.py`).

---

## Healthy reference (what a correct container prints)

```json
{
  "cred_class": "google.auth.compute_engine.credentials.Credentials",
  "has_impersonation": false,
  "GOOGLE_APPLICATION_CREDENTIALS": "(unset)",
  "token_email": "<your runtime SA, or the reasoning-engine service agent>",
  "token_scope": "... https://www.googleapis.com/auth/cloud-platform ...",
  "has_cloud_platform": true,
  "create_session_http": 200,
  "create_session_status": "OK"
}
```

A correctly-configured runtime — default identity **or** a plain custom SA —
resolves ADC to the **metadata server** (`compute_engine.Credentials`), carries
`cloud-platform` in its scope, and gets **HTTP 200** from `CreateSession`.

## Reading your output — divergence points to the fix

| What your probe shows | Cause | Fix |
|---|---|---|
| `has_cloud_platform: false` / `create_session_reason: ACCESS_TOKEN_SCOPE_INSUFFICIENT` | Runtime token lacks the `cloud-platform` scope | See the matching row below — scope comes from *how the token is minted*, never from a role grant. |
| `GOOGLE_APPLICATION_CREDENTIALS` is a **file path** (not `(unset)`) | A key/credential file is overriding ADC inside the container | Remove that env var / file so the runtime uses the metadata identity (which carries `cloud-platform`). |
| `cred_class` is `…external_account…` **or** `has_impersonation: true` | Runtime identity is **federated / Workload Identity Federation**; scope is pinned in that credential config | Either switch to the default managed identity (drop the custom SA) **or** add `https://www.googleapis.com/auth/cloud-platform` to the scope list in the federation/impersonation config. |
| `cred_class` is `compute_engine…` but scope still lacks `cloud-platform` | Something in your code requested a narrow scope | Search your deploy/agent code for `scopes=` / `target_scopes=`; include `cloud-platform` or remove the override. |
| Output matches the healthy reference but the real agent still 403s | Not the runtime token | Check that your session store (`SESSION_ENGINE_ID`) is not in a **different project**. |

---

## The most reliable fix

If you don't need a specific runtime identity, run the engine on the **default
managed identity** (omit `RUNTIME_SERVICE_ACCOUNT`) and grant `roles/aiplatform.user`
to that identity. The default identity always receives a `cloud-platform` token
from the metadata server — no impersonation, no federation, no scope to pin
incorrectly. If you must keep a custom SA, ensure it is a **plain** service
account (not a federated principal) and that the two bindings above are in place;
a plain custom SA also receives a `cloud-platform` metadata token.

## Files

| File | Purpose |
|---|---|
| `agent.py` | The probe agent (`query` reports cred class, scopes, and a live `CreateSession`). |
| `deploy.py` | Build → run probe in-container → print JSON → tear down. Env-configured. |
| `destroy.py` | Delete an engine left by a `KEEP_ENGINE=1` deploy. |
| `requirements.txt` | Deploy-host dependencies. |
