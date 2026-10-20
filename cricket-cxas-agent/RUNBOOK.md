# Runbook: deploy the Cricket Care troubleshooting agent into a new project

Everything project-specific lives in `.env`. Pointing the bundle at another Google Cloud
project is a config change plus the commands below. Budget about an hour the first time, most of it waiting on the server build and the test suite.
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
```

`deploy/prep.sh` (step 3) enables the APIs.

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
| `DATASTORE_ID`, `FIRESTORE_DATABASE`, `FIRESTORE_LOCATION`, `RESUME_WINDOW_MINUTES`, `EXTRACT_MODEL` | keep the example values |
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM`, `DEMO_SMS_NUMBER` | optional. Fill all four to have the agent text the guide link to `DEMO_SMS_NUMBER` (a Twilio trial only sends to numbers verified in Twilio). Leave empty and the agent says it could not text and reads the link instead. |

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pytest -q
```

Expect `64 passed`. A warning about ffmpeg is harmless.

## 3. Prep

```bash
deploy/prep.sh
```

Enables the APIs, makes sure the agent platform's service agent exists, creates the Firestore
`(default)` database in Native mode if the project has none, installs the Python packages, and
creates the Agent Search data store `cricket-tutorials` with its schema. Safe to rerun.

## 4. Content

```bash
deploy/content.sh            # from the tutorials already in knowledge/raw
deploy/content.sh --scrape   # scrape the support site again first (headless browser, about an hour)
```

Runs on your machine:

| Stage | What it does |
|---|---|
| Scrape (only with `--scrape`) | Reads every tutorial for the devices in `knowledge/raw` from the support site |
| Label | Gemini marks which steps end the call and writes symptoms and a summary. Cached per tutorial, so only new or changed tutorials are sent |
| Build | Writes `knowledge/catalog`. The hand review in `knowledge/step_review.json` is applied on top: each step is marked as dropping the call, might drop it, or safe |
| Load | Upserts one document per tutorial into the data store and removes tutorials that are gone. Search sees changes within a few minutes |

Rerun this whenever tutorials change. The agent needs no redeploy for new content.

## 5. Deploy and test

```bash
deploy/deploy.sh             # app, server, connection, then the typed suite
deploy/deploy.sh --no-test   # deploy only
```

| Step | What it does |
|---|---|
| Agent app | Creates or updates app `cricket-care` with the live model: the Care Concierge, Tech Support, the `search_tutorials` data store tool, the `next_step` step tool, its variables and callbacks |
| Support server | Builds and deploys the private Cloud Run service `cricket-support-mcp` (one always-warm instance). Takes 3 to 5 minutes |
| Access | Lets the server use Firestore and lets the agent platform call the server |
| Connect | Creates the `support` toolset and binds its tools to Tech Support. Expect `toolsets on agent: [('support', 10)]` |
| Typed suite | Plays the scripted callers in `bootstrap/suite_a.json` |

To run the suite again, or only some scenarios:

```bash
.venv/bin/python bootstrap/run_suite.py            # all scenarios
.venv/bin/python bootstrap/run_suite.py P3 P8      # a subset
```

Before each scenario the runner resets the demo account to that scenario's profile and clears any
saved place. P8 drops the call at the restart and calls back in a new session. Each run creates
`runs/<UTC timestamp>/`:

| File | Contents |
|---|---|
| `summary.md` | PASS or FAIL per scenario, then every transcript. Read this first |
| `P1.json` … `P8.json` | Full record per scenario: caller and agent text, tool calls, raw responses, session ids |

A FAIL means an expected tool was not called or a forbidden one was. To put the demo account in a
given state for manual testing: `.venv/bin/python bootstrap/demo_reset.py P4`.

## 6. Voice

1. Console → Customer Engagement Suite → the `cricket-care` app.
2. Create a version, then a deployment from it.
3. In the telephony settings, bind a phone number to that deployment.
4. Call it and say "my wifi is really slow". The account starts in profile P3 (clean account,
   iPhone on the calling line). Run `demo_reset.py` with another profile to try the others.
5. To try a callback, let it walk you to the restart step, say you're okay to call back, hang up,
   and call again within 30 minutes.
6. Note the conversation id shown in the console for each call, and anything that sounded
   wrong (reading long lists, talking over you, long silences).

Console menu names may differ slightly from the above; the order of the steps does not.

## How a call works

| Part | Where it runs | Role |
|---|---|---|
| `search_tutorials` | Agent platform, data store tool | Finds tutorials for the caller's words, filtered to their phone |
| `agents/tech_support/after_tool.py` | Agent platform, callback | Drops results for other phones, keeps the steps out of the model's view, loads a saved place on callback |
| `agents/tech_support/next_step.py` | Agent platform, Python tool | Gives one step at a time. Holds a step that ends the call until the caller says yes, and any step that ends or might drop the call until its place is saved |
| `agents/tech_support/before_tool.py` | Agent platform, callback | Fills `save_progress` with the caller's place, so the model never copies it |
| `get_progress`, `save_progress` | Support server | Keep the caller's place in Firestore `progress/{customer_id}`, used once within `RESUME_WINDOW_MINUTES` |
| Account tools, `send_guide_link`, `open_ticket` | Support server | Demo account checks and outreach |

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `create_app.py` fails with permission denied | The application-default login is a different user, or lacks the platform admin role | Rerun `gcloud auth application-default login` as the project user |
| Any API error mentioning a quota project | Quota project not set for application default credentials | `gcloud auth application-default set-quota-project "$PROJECT"` |
| `deploy.sh` fails at the build | Cloud Build service account lacks permissions, common in managed orgs | Ask the org admin for the default Cloud Build setup, or grant the build service account Cloud Run and Artifact Registry roles |
| `deploy.sh` fails granting the invoker role on `gcp-sa-ces` | An org policy limits which identities can be granted roles | Ask the org admin to allow Google-managed service agents |
| `content.sh` stops with "steps are … bytes encoded" | A tutorial is too large for the search tool, which silently drops results of about 16 KB | Split the tutorial, or raise the limit in `knowledge/load_datastore.py` only after testing it |
| The build prints "review entry no longer matches the step text" | A scraped tutorial changed under a hand-reviewed step | Recheck that step and update `knowledge/step_review.json` |
| Turns print `(429 quota; retry in …)` | Token quota at the default | Wait for it, or raise the quota (step 1) |
| The agent says it found nothing for a common problem right after `content.sh` | The data store is still indexing | Wait a few minutes |

## Known behaviour

- One turn uses about 4,000 tokens. The runner retries rate-limited turns four times with growing
  waits.
- `next_step` must stay the first function in its file: the platform takes the first one as the tool.
- Set `MCP_WIRE_LOG=1` in `.env` and redeploy to log every request to the server. Useful for
  debugging tool calls; noisy otherwise.

## Tear down

```bash
deploy/teardown.sh           # asks first; --yes skips the question
```

Deletes the app, the Cloud Run service, the data store, and the saved progress. It keeps the
enabled APIs and the Firestore database itself (deleting a project's `(default)` database blocks
re-creating it for a while). The server images stay in the Artifact Registry repository
`cloud-run-source-deploy`; delete it with
`gcloud artifacts repositories delete cloud-run-source-deploy --location us-central1` if no other
Cloud Run service in the project was deployed from source.
