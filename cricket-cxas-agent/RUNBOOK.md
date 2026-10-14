# Runbook: deploy the Cricket Care troubleshooting agent into a new project

Everything project-specific lives in `.env`. Pointing the bundle at another Google Cloud
project is a config change plus the commands below. Budget about 45 minutes the first time.

## 0. What you need

| Item | Notes |
|---|---|
| A Google Cloud project with billing enabled | Owner or Editor on it. CES quotas there should be above the 1000 tokens/min default (check in step 1). |
| `gcloud` CLI, authenticated as a user on that project | `gcloud auth login` then `gcloud auth application-default login` so the Python SDK picks up the same identity. |
| Python 3.12+ | The MCP server image pins its own runtime in the `Dockerfile`. |
| This folder (`cricket-cxas-agent/`) checked out | Including `knowledge/catalog/*.json`, which the server bakes into the image. |

## 1. Enable APIs and confirm quota

```bash
PROJECT=<your-project-id>
gcloud config set project "$PROJECT"
gcloud services enable ces.googleapis.com run.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com cloudquotas.googleapis.com
```

Console → IAM & Admin → Quotas & System Limits → filter service **Gemini Enterprise for Customer
Experience API** → quota **RunSession LLM tokens per minute per project per region per base model**
→ row region `us-central1`, base model `gemini-3.1-flash-live`. Anything from 10,000 up is
comfortable for one call at a time. If it reads 1000, request an increase before step 5.

## 2. Configure

```bash
cp .env.example .env
```

Set at least:

| Key | Value |
|---|---|
| `GOOGLE_CLOUD_PROJECT`, `CXAS_PROJECT` | your project id |
| `CXAS_LOCATION` | `us` (the agent platform region) |
| `GOOGLE_CLOUD_LOCATION` | `us-central1` (the Cloud Run region) |
| `CARE_APP_ID` | `cricket-care` |
| `CARE_LIVE_MODEL` | `gemini-3.1-flash-live` |
| `DEMO_CUSTOMER_ID` | `cust_2001` |
| `DEMO_PROFILE` | `P3` (clean account, the default demo) |
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM` | optional; without them the agent says it could not text and reads the link |

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pytest -q          # expect 38 passed; proves the catalogs and tools load
```

## 3. Deploy the support MCP server

```bash
./deploy_mcp.sh
```

This builds from the bundle root, deploys a private Cloud Run service `cricket-support-mcp` with
one always-warm instance, and grants `roles/run.invoker` to the platform's service agent
(`service-<project-number>@gcp-sa-ces.iam.gserviceaccount.com`). The last line prints the MCP
endpoint; copy it. If the service agent does not exist yet, create it once with

```bash
gcloud beta services identity create --service=ces.googleapis.com --project="$PROJECT"
```

and rerun the deploy.

## 4. Create the app and attach the toolset

```bash
.venv/bin/python bootstrap/create_app.py
.venv/bin/python bootstrap/attach_support_toolset.py https://<service-url>/mcp
```

The first command creates app `cricket-care` with the live model, the Care Concierge root agent,
and the Tech Support child. The second creates the `support` toolset over the MCP endpoint and
binds all eleven tools to Tech Support by id. The output should show
`toolsets on agent: [('support', 11)]`. Both scripts are idempotent.

## 5. Run the typed suite and capture the evidence

```bash
.venv/bin/python bootstrap/run_suite.py            # all seven profiles
.venv/bin/python bootstrap/run_suite.py P3 P4      # or a subset
```

Each run writes `runs/<UTC timestamp>/`:

| File | Contents |
|---|---|
| `summary.md` | One table, PASS or FAIL per scenario on expected and forbidden tools, then every transcript |
| `P1.json` … `P7.json` | Full turn-by-turn record: caller text, agent text, tool spans, raw platform response, session id |

To share a run, zip that folder or commit it on the branch. The session ids inside let anyone
with console access open the matching conversation and trace.

Scripts and pass criteria are in `bootstrap/suite_a.json`; edit the turns there, not the runner.
To switch the demo account state between manual tests: `.venv/bin/python bootstrap/demo_reset.py P4`.

## 6. Voice (M2)

1. Console → the `cricket-care` app → Deploy → create a version and a deployment.
2. Integrations → Telephony → bind a phone number to that deployment.
3. Call it. Say "my wifi is really slow" and follow the steps. The P3 profile is seeded by default.
4. For the record, note the conversation id from the console; it can be fetched later with the
   platform's conversation API and added to the run folder.

## Known behaviour

- A turn costs about 4,000 tokens. At the default 1000 tokens/min quota most turns return 429; the
  runner retries four times with growing waits, so a seven-scenario run can take 20 minutes.
- Without `tool_ids` on the agent toolset binding the agent silently has no tools. The attach
  script sets them; do not rebind the toolset by hand in the console.
- `create_app.py` updates instructions and direct tools only. It never touches the toolset binding.
- `MCP_WIRE_LOG=1` in `.env` makes the server log every MCP request body. Useful once; noisy after.

## Tear down

```bash
gcloud run services delete cricket-support-mcp --region us-central1 --project "$PROJECT" --quiet
```

Delete the app from the console (or with the platform API). Nothing else is created.
