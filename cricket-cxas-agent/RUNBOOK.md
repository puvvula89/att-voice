# Runbook: deploy the Cricket Care troubleshooting agent into a new project

Everything project-specific lives in `.env`. Pointing the bundle at another Google Cloud
project is a config change plus the commands below. Budget about 45 minutes the first time.
Run every command from the `cricket-cxas-agent/` folder.

## 0. What you need

| Item | Notes |
|---|---|
| A Google Cloud project with billing enabled | Owner, or these roles: Customer Engagement Suite admin, Cloud Run admin, Cloud Build editor, Service Usage admin, Project IAM admin. |
| `gcloud` CLI | Logged in as a user on that project (step 1 does the login). |
| Python 3.10 or newer | Check with `python3 --version`. The server image uses its own Python. |
| This repository | `git clone https://github.com/puvvula89/att-voice.git && cd att-voice/cricket-cxas-agent` |

## 1. Log in, enable APIs, confirm quota

```bash
PROJECT=<your-project-id>
gcloud auth login
gcloud auth application-default login
gcloud config set project "$PROJECT"
gcloud auth application-default set-quota-project "$PROJECT"
gcloud services enable ces.googleapis.com run.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com
```

The two logins are both needed. `gcloud` commands use the first; the Python scripts use the
second (application default credentials).

**Check the quota before going further.** Console → IAM & Admin → Quotas & System Limits. In the
filter, search for the service by its display name, **Gemini Enterprise for Customer Experience
API** (searching `ces.googleapis.com` finds nothing). Find **RunSession LLM tokens per minute per
project per region per base model**, row region `us-central1`, base model `gemini-3.1-flash-live`.

| Value | What to expect |
|---|---|
| 10,000 or more | Comfortable for one conversation at a time. |
| 1,000 (the default) | Most turns get rate-limited. Everything still works but the suite takes 20+ minutes. Request an increase. |

## 2. Configure and test locally

```bash
cp .env.example .env
```

Edit `.env`:

| Key | Value |
|---|---|
| `GOOGLE_CLOUD_PROJECT` | your project id (required) |
| `CXAS_PROJECT` | leave commented out unless the agent app lives in a different project |
| `CXAS_LOCATION` | `us` (the agent platform region; keep as is) |
| `GOOGLE_CLOUD_LOCATION` | `us-central1` (the Cloud Run region; keep as is) |
| `CARE_APP_ID`, `CARE_LIVE_MODEL`, `DEMO_CUSTOMER_ID`, `SUPPORT_MCP_SERVICE`, `DEMO_PROFILE` | keep the example values |
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM`, `DEMO_SMS_NUMBER` | optional. Fill all four to have the agent text the guide link to `DEMO_SMS_NUMBER` (a Twilio trial only sends to numbers verified in Twilio). Leave empty and the agent says it could not text and reads the link instead. |

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pytest -q
```

Expect `38 passed`. A warning about ffmpeg is harmless.

## 3. Create the app

```bash
.venv/bin/python bootstrap/create_app.py
```

Creates app `cricket-care` with the live model, the Care Concierge root agent, and the Tech
Support child agent. Safe to rerun; it updates in place. This comes before the server deploy
because creating the first app also creates the platform's service agent, which step 4 grants
access to.

## 4. Deploy the support MCP server

```bash
./deploy_mcp.sh
```

Builds the server image from this folder, deploys a private Cloud Run service
`cricket-support-mcp` with one always-warm instance, and lets the platform's service agent
(`service-<project-number>@gcp-sa-ces.iam.gserviceaccount.com`) call it. Takes 3 to 5 minutes.
The last lines print the endpoint, for example:

```
MCP endpoint: https://cricket-support-mcp-abc123-uc.a.run.app/mcp
```

Copy that URL, including `/mcp`, for the next step.

## 5. Attach the toolset

```bash
.venv/bin/python bootstrap/attach_support_toolset.py https://<the-url-from-step-4>/mcp
```

Creates the `support` toolset over the endpoint and binds its eleven tools to Tech Support.
Success looks like:

```
   toolsets on agent: [('support', 11)]
```

If the count is 0 or the line is missing, stop and fix that first; the agent will otherwise
answer without any tools.

## 6. Run the typed suite and share the results

```bash
.venv/bin/python bootstrap/run_suite.py            # all seven scenarios
.venv/bin/python bootstrap/run_suite.py P3 P4      # or a subset
```

Before each scenario the runner resets the demo account to that scenario's profile, then plays
the scripted caller turns and records what the agent said and which tools it called. Each run
creates `runs/<UTC timestamp>/`:

| File | Contents |
|---|---|
| `summary.md` | PASS or FAIL per scenario, then every transcript. Read this first. |
| `P1.json` … `P7.json` | Full record per scenario: caller and agent text, tool calls, raw platform response, session id. |

A FAIL means an expected tool was not called or a forbidden one was. It points at the agent's
behaviour, not at the deployment, as long as step 5 showed 11 tools.

To share a run, commit and push the folder:

```bash
git add runs/<timestamp> && git commit -m "Add suite run <timestamp>" && git push
```

The scripts and pass criteria live in `bootstrap/suite_a.json`. To put the demo account in a
given state for manual testing: `.venv/bin/python bootstrap/demo_reset.py P4`.

## 7. Voice

1. Console → Customer Engagement Suite → the `cricket-care` app.
2. Create a version, then a deployment from it.
3. In the telephony settings, bind a phone number to that deployment.
4. Call it and say "my wifi is really slow". The account starts in profile P3 (clean account,
   iPhone on the calling line). Run `demo_reset.py` with another profile to try the others.
5. Note the conversation id shown in the console for each call, and anything that sounded
   wrong (reading long lists, talking over you, long silences).

Console menu names may differ slightly from the above; the order of the steps does not.

## Tutorial content

The support server reads tutorials from Firestore (`CONTENT_BACKEND=firestore`, set by `deploy_mcp.sh`) and
reloads within `CONTENT_CHECK_SECONDS` whenever `meta/content.version` changes. Content updates never need a redeploy.

```bash
.venv/bin/python -m knowledge.enrich --workers 2      # Gemini labels: safety flags, symptoms, summaries (cached)
.venv/bin/python -m knowledge.build_catalog           # apply labels; disagreements -> knowledge/enrichment/review.jsonl
.venv/bin/python -m knowledge.load_firestore --dry-run
.venv/bin/python -m knowledge.load_firestore          # upsert changed tutorials, bump the version
```

The Firestore `(default)` database must exist in Native mode. `deploy_mcp.sh` grants the service's runtime
account `roles/datastore.user`. A caller's place in a tutorial is kept in `progress/{customer_id}` for
`RESUME_WINDOW_MINUTES`.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `create_app.py` fails with permission denied | The application-default login is a different user, or lacks the platform admin role | Rerun `gcloud auth application-default login` as the project user |
| Any API error mentioning a quota project | Quota project not set for application default credentials | `gcloud auth application-default set-quota-project "$PROJECT"` |
| `deploy_mcp.sh` fails at the build | Cloud Build service account lacks permissions, common in managed orgs | Ask the org admin for the default Cloud Build setup, or grant the build service account Cloud Run and Artifact Registry roles |
| `deploy_mcp.sh` fails granting the invoker role on `gcp-sa-ces` | The service agent does not exist yet, or an org policy limits which identities can be granted roles | Make sure step 3 ran first. If it still fails, ask the org admin to allow Google-managed service agents |
| Turns print `(429 quota; retry in …)` | Token quota at the default | Wait for it, or raise the quota (step 1) |
| Agent replies but step 5 printed 0 tools | Toolset bound without tool ids | Rerun step 5; do not edit the toolset by hand in the console |

## Known behaviour

- One turn uses about 4,000 tokens. The runner retries rate-limited turns four times with growing
  waits.
- `create_app.py` updates instructions only. It never touches the toolset binding, so you do not
  need to rerun step 5 after editing instructions.
- Set `MCP_WIRE_LOG=1` in `.env` and redeploy to log every request to the server. Useful for
  debugging tool calls; noisy otherwise.

## Tear down

```bash
gcloud run services delete cricket-support-mcp --region us-central1 --project "$PROJECT" --quiet
gcloud artifacts repositories delete cloud-run-source-deploy --location us-central1 --project "$PROJECT" --quiet
```

Delete the `cricket-care` app from the console. Skip the second command if other Cloud Run
services in the project were also deployed from source; they share that image repository.
