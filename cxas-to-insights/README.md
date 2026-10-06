# CES conversations into CX Insights

How to confirm whether a CES agent app (CX Agent Studio) is sending conversations
to Customer Experience Insights, what to change if it is not, and a test that
proves it end to end.

Verified against `ces.googleapis.com/v1beta` and
`contactcenterinsights.googleapis.com/v1` on 2026-10-05, including a full
cold-start run from disabled APIs.

**Read this first:** ingestion is **native and on by default**. CES and CX
Insights share Google-managed storage — per the CX Agent Studio
[Conversation history](https://docs.cloud.google.com/gemini-enterprise-cx/cx-agent-studio/conversation-history)
docs, Spanner is *"used by CX Agent Studio **and CX Insights** to surface
conversation history"*. There is no export job, no pipeline and no ingestion
setting. The Insights API is also a hard dependency of the CES API, so it
cannot be switched off on a project running agents.

So when conversations are missing, you are not looking for a feature to enable.
You are looking for one of five things suppressing or hiding them:

| # | Cause | Symptom |
|---|---|---|
| 1 | `disableConversationLogging: true` on the app | Nothing in Insights, CES history *or* the Monitor dashboard |
| 2 | Traffic is from the **simulator** | Nothing in Insights, ever, regardless of config |
| 3 | Caller lacks the **Insights IAM role** | `403`, or "Access Denied" in the console |
| 4 | Browser on the **wrong Google account** | "Access Denied" that looks exactly like cause 3 |
| 5 | Wrong **location / endpoint** | Everything works; the list just looks empty |

Work through Part 1 before changing anything.

---

# Part 1 — Check what you have today

Four checks against the live project. None of them change anything.

```bash
PROJECT=ATT_PROJECT; LOC=us; APP=THEIR_APP_ID
TOKEN=$(gcloud auth print-access-token)
```

`LOC` is the CES app location — `us`, `eu` or `global`. It is not a GCP region.

### 1.1 Are the APIs enabled?

```bash
gcloud services list --enabled --project=$PROJECT \
  | grep -E "ces\.|contactcenterinsights|dialogflow|speech|dlp"
```

`contactcenterinsights.googleapis.com` is a **dependency of** `ces.googleapis.com`,
so if agents are running it is already enabled. Verified both directions:

```
$ gcloud services enable ces.googleapis.com        # on an empty project
$ gcloud services list --enabled
ces.googleapis.com
contactcenterinsights.googleapis.com               <-- pulled in automatically

$ gcloud services disable contactcenterinsights.googleapis.com
FAILED_PRECONDITION: ... is depended on by the following active service(s):
ces.googleapis.com
```

This is almost never the cause. Confirm and move on.

### 1.2 Is the app allowed to log? *(the one real off-switch)*

```bash
curl -s -H "Authorization: Bearer $TOKEN" -H "x-goog-user-project: $PROJECT" \
  "https://ces.googleapis.com/v1beta/projects/$PROJECT/locations/$LOC/apps/$APP" \
  | python3 -m json.tool | grep -A6 loggingSettings
```

The field is **opt-out** — absent means logging is ON. A healthy app returns:

```json
"loggingSettings": {
  "conversationLoggingSettings": { "retentionWindow": "31536000s" }
}
```

| Result | Meaning |
|---|---|
| No `disableConversationLogging`, or `false` | Logging ON — continue to 1.3 |
| `"disableConversationLogging": true` | **This is the cause.** Nothing is retained |
| No `loggingSettings` at all | All defaults — logging ON |

Three things to know if it is `true`:

- It is a **deliberate opt-out** someone configured. Ask why before reversing it —
  it is often a privacy or data-residency decision.
- It is **not retroactive.** Past conversations were never stored and cannot be
  recovered.
- **BigQuery export keeps working while it is set** — per the docs it disables
  *"all types of long-term conversational data except BigQuery data"*. Check
  `bigqueryExportSettings` for a surviving record.

While you are here, read `metricAnalysisSettings.llmMetricsOptedOut` too. If
`true`, conversations still arrive but sentiment, topics and outcomes are empty —
which a business user will report as "Insights isn't working".

**Run this against every app, not one.** A mix of settings explains the confusing
case where some agents' conversations appear and others' do not:

```bash
for APP in $(curl -s -H "Authorization: Bearer $TOKEN" -H "x-goog-user-project: $PROJECT" \
  "https://ces.googleapis.com/v1beta/projects/$PROJECT/locations/$LOC/apps" \
  | python3 -c "import sys,json;[print(a['name'].split('/')[-1]) for a in json.load(sys.stdin).get('apps',[])]"); do
  echo -n "$APP: "
  curl -s -H "Authorization: Bearer $TOKEN" -H "x-goog-user-project: $PROJECT" \
    "https://ces.googleapis.com/v1beta/projects/$PROJECT/locations/$LOC/apps/$APP" \
  | python3 -c "import sys,json;d=json.load(sys.stdin).get('loggingSettings',{}).get('conversationLoggingSettings',{});print('DISABLED' if d.get('disableConversationLogging') else 'logging ON')"
done
```

### 1.3 Is anything actually in Insights?

This is the check that separates "it works, you just cannot see it" from "data is
not arriving".

```bash
curl -s -H "Authorization: Bearer $TOKEN" -H "x-goog-user-project: $PROJECT" \
  "https://$LOC-contactcenterinsights.googleapis.com/v1/projects/$PROJECT/locations/$LOC/conversations?pageSize=5"
```

| Result | Cause | Go to |
|---|---|---|
| Conversations returned | Ingestion works — it is an **access** problem | 2.2, 2.3 |
| `{}` / zero | Data is not arriving | 1.2, then 2.4 |
| `403` | Caller lacks the Insights role | 2.2 |
| `400 Location Mismatch` | Wrong endpoint host for the location | 2.5 |

### 1.4 Who actually holds the Insights role?

```bash
gcloud projects get-iam-policy $PROJECT \
  --flatten="bindings[].members" \
  --filter="bindings.role:contactcenterinsights" \
  --format="value(bindings.role,bindings.members)"
```

Project Owner does **not** imply Insights access. An empty result here, combined
with conversations returned in 1.3, is the most common real-world answer: the
data has been flowing all along and nobody was granted the role.

---

# Part 2 — Enable and configure

Only do the steps Part 1 flagged.

### 2.1 Enable the APIs

Idempotent — safe to run even if already enabled.

```bash
gcloud services enable \
  ces.googleapis.com \
  contactcenterinsights.googleapis.com \
  dialogflow.googleapis.com \
  speech.googleapis.com \
  storage.googleapis.com \
  dlp.googleapis.com \
  --project=$PROJECT
```

| API | Needed for |
|---|---|
| `ces` | The agent app. Pulls in `contactcenterinsights` + `storage` |
| `contactcenterinsights` | CX Insights. Auto-enabled above |
| `dialogflow` | Dialogflow runtime integration, topic modeling |
| `speech` | Transcribing audio conversations |
| `dlp` | Redaction of transcripts and audio |

A text conversation reached Insights in testing without `dialogflow`, `speech`
or `dlp` enabled at call time — they serve the features listed, not base chat
ingestion.

### 2.2 Grant the Insights IAM role

```bash
gcloud projects add-iam-policy-binding $PROJECT \
  --member=user:SOMEONE@example.com \
  --role=roles/contactcenterinsights.editor
```

`roles/contactcenterinsights.viewer` is enough for read-only access. Confirm it
took effect rather than trusting the console — note there is no
`gcloud projects test-iam-permissions` subcommand, it is a REST call:

```bash
curl -s -X POST \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  "https://cloudresourcemanager.googleapis.com/v1/projects/$PROJECT:testIamPermissions" \
  -d '{"permissions":["contactcenterinsights.conversations.list","contactcenterinsights.conversations.get"]}'
```

IAM bindings survive an API being disabled and re-enabled — verified.

### 2.3 Sign in as the right Google account

If the permissions above are held and the console still says **"Access Denied —
The caller does not have permission"**, the browser is authenticated as a
*different* Google account. This is indistinguishable from a real permissions
problem and wastes the most time of anything here.

- `authuser=N` is positional and not stable — bumping it is guesswork.
- Use a browser profile or incognito window signed in **only** as the account
  holding the role.
- Google is migrating the console to `console.cloud.google` / `auth.cloud.google`
  (no `.com`). Those are genuine — verified by a Google Trust Services
  certificate for `*.cloud.google` — even though the published
  [required-domains list](https://docs.cloud.google.com/docs/get-started/required-domains)
  still shows only the `.com` forms.

### 2.4 Re-enable conversation logging

Only if 1.2 found `disableConversationLogging: true`, and only after confirming
why it was set.

```bash
curl -X PATCH -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" -H "x-goog-user-project: $PROJECT" \
  "https://ces.googleapis.com/v1beta/projects/$PROJECT/locations/$LOC/apps/$APP?updateMask=loggingSettings.conversationLoggingSettings.disableConversationLogging" \
  -d '{"loggingSettings":{"conversationLoggingSettings":{"disableConversationLogging":false}}}'
```

Or untick **"Log your customer conversations"** in the console.

### 2.5 Use the right location and endpoint

Two rules. Breaking either returns an empty list or a `400` that reads like a
permissions problem:

1. **A CES app in `us` maps to Insights location `us`** — the multiregion, the
   same string. Not `us-central1`. Verified: conversations landed in `us` while
   `us-central1` and `global` stayed empty.
2. **The endpoint host prefix must match the location.** Only `global` is served
   by the unprefixed host.

| CES app location | Insights location | Endpoint |
|---|---|---|
| `us` | `us` | `https://us-contactcenterinsights.googleapis.com` |
| `eu` | `eu` | `https://eu-contactcenterinsights.googleapis.com` |
| `global` | `global` | `https://contactcenterinsights.googleapis.com` |

```
400  Location Mismatch: Server location `global` and
     resource location `us` do not match
```

That error is about the **host**, not the path.

### 2.6 Send LIVE traffic, not simulator traffic

Every conversation carries a `source`: `LIVE`, `SIMULATOR`, `EVAL` or
`AGENT_TOOL`. **Insights reports on `LIVE` only.** A conversation started from
the CX Agent Studio simulator is recorded as `SIMULATOR` and will never appear,
however the app is configured. This is the single most common false alarm.

A deployed channel, a real client or a direct API call all produce `LIVE`.
**A deployment is not required for ingestion** — a verified conversation ran
against the draft app with no deployment and still reached Insights.

---

# Part 3 — Run the test

Proves the whole path on a project you control, using a throwaway demo app.

```bash
cp .env.example .env     # set GOOGLE_CLOUD_PROJECT, CXAS_LOCATION, INSIGHTS_LOCATION
gcloud auth login        # as the account holding the Insights role

python bootstrap/deploy_app.py        # app -> agent -> version -> deployment (~10 min)
python verify/run_conversation.py     # 3-turn LIVE conversation, waits for history
python verify/check_insights.py       # all gates + the conversation in Insights
```

`ces_client.py` holds the shared REST helper and derives the regional Insights
endpoint from `INSIGHTS_LOCATION`. Everything uses `gcloud` for the token and
`urllib` for the calls — no SDK pinning to get wrong on another machine, and
`python-dotenv` is optional.

**What success looks like:**

```
2. CES conversation history
   verify-20c8d4d69296  source=LIVE  turns=2  deployment=deploy-0001

3. Insights conversations (us-contactcenterinsights.googleapis.com, location=us)
   verify-20c8d4d69296  medium=CHAT  turns=2  agentId=insights-demo
   verify-20c8d4d69296: FOUND in Insights
```

Then confirm the same thing in the console:

- `https://ccai.cloud.google.com/insights/projects/PROJECT_ID`
- or CX Agent Studio → the app → **Monitor** → **View Conversations**

Set the console's region selector to the **US multiregion** to match.

**Allow time.** A conversation is written only once the **session ends**, and
took about **90 seconds** to appear.

### Tearing down

```bash
curl -X DELETE -H "Authorization: Bearer $TOKEN" -H "x-goog-user-project: $PROJECT" \
  "https://ces.googleapis.com/v1beta/projects/$PROJECT/locations/$LOC/apps/insights-demo?force=true"
```

---

# Reference

## Where conversations live when nobody uses Insights

CES keeps its own history regardless. Nothing is lost while Insights goes unused.

| Where | How to review it |
|---|---|
| CES conversation history | CX Agent Studio → the agent → agent preview → conversation history button |
| Monitor dashboard | CX Agent Studio → **Monitor**: total sessions, escalation rate, turns/session, E2E latency, tool failure rate |
| CES API | `GET .../apps/{app}/conversations` and `/conversations/{id}` |
| CX Insights | The same conversations, plus transcript search, sentiment, topics, QA |

Retention follows `conversationLoggingSettings.retentionWindow` — **365 days by
default, 2 years maximum**.

Customer-owned sinks, genuinely off until configured. These are a **parallel**
path for your own analytics, not how Insights gets its data:

| Sink | Field |
|---|---|
| BigQuery export | `loggingSettings.bigqueryExportSettings` `{enabled, project, dataset}` (plus an `unredacted` variant) |
| Cloud Logging | `loggingSettings.cloudLoggingSettings.enableCloudLogging` |
| Audio in Cloud Storage | `loggingSettings.audioRecordingConfig.gcsBucket` |

Cross-project BigQuery or Storage needs the CES service agent
`service-<PROJECT_NUMBER>@gcp-sa-ces.iam.gserviceaccount.com` granted
`roles/bigquery.admin` or `storage.objects.create`.

`App.dashboardSettings.defaultDashboard` only embeds an existing Insights
dashboard into the Monitoring view. It does **not** control ingestion.

The Dialogflow runtime-integration toggles ("Send data to Insights" in Agent
Assist, "Enable Conversation History" in Dialogflow CX) apply to
Dialogflow/Agent Assist virtual agents, **not** to CES apps.

## Gotchas

| Symptom | Cause |
|---|---|
| `CreateApp` fails with bare *"an internal error has occurred"* | `modelSettings.model` is effectively required; `displayName` alone is not enough |
| `The model gemini-2.5-flash is not available in us` | Model must exist in the CES location. `gemini-3.5-flash` works in `us` |
| `User-specified resource ID 'root' must match '[a-zA-Z0-9][a-zA-Z0-9-_]{4,35}'` | IDs must be 5–36 chars. `root` is too short; `concierge` is fine |
| `CreateDeployment` rejects resource ID `'-'` | The documented draft alias `versions/-` is **not** accepted. Cut a real app version |
| Sessions fail with no root agent | Creating the agent does not wire it up — `PATCH` the app's `rootAgent` |
| Create calls appear to hang | LROs. Agent, version and deployment each took **over 200s** in a cold-start run while still succeeding. A poll timeout is not a failure |
| `429 RESOURCE_EXHAUSTED` mid-conversation | Low default model quota on a fresh project. The scripts retry with backoff |
| Conversation missing right after the call | Only written when the **session ends**; ~90s lag |
| `400 Location Mismatch` | Wrong endpoint host for the location |
| Insights empty at `us-central1` | A CES app in `us` maps to the `us` multiregion |
| Console "Access Denied" with permissions held | Browser on a different Google account |
| `gcloud projects test-iam-permissions` not found | No such subcommand. Use `get-iam-policy` or the REST endpoint |

## What was verified

Validated twice: incrementally, then as a **full cold start** — all CES and
Insights APIs disabled (`403 SERVICE_DISABLED` on both), every app and
conversation deleted, then this document followed from the top.

| Claim | Result |
|---|---|
| Insights API is a dependency of CES | Yes — both directions |
| APIs enable from a fully disabled state | Yes |
| IAM bindings survive API disable/re-enable | Yes |
| app → agent → version → deployment | Rebuilt from scratch by `deploy_app.py` |
| Conversation logging ON by default | Yes — on a fresh app, both runs |
| API traffic yields `source: LIVE` | Yes — simulator yields `SIMULATOR` |
| Conversation lands in CES history | Yes — ~90s after session end |
| Conversation reaches Insights | Yes — `verify-20c8d4d69296` via the regional endpoint |
| Visible in the CX Insights console | Yes — US multiregion |
| Works without a deployment | Yes |
