# CES conversations into CX Insights

A reproducible setup for getting conversations from a CES agent app (CX Agent
Studio) into Customer Experience Insights, plus the scripts used to prove each
step.

**Status: verified end to end** on 2026-10-05 against `ces.googleapis.com/v1beta`
and `contactcenterinsights.googleapis.com/v1`. A CES conversation was observed in
Insights with its full transcript, turn count, labels and analysis.

---

## The short answer

**Ingestion is native and on by default.** CES and CX Insights share Google-managed
storage — per the CX Agent Studio
[Conversation history](https://docs.cloud.google.com/gemini-enterprise-cx/cx-agent-studio/conversation-history)
docs, Spanner is *"used by CX Agent Studio **and CX Insights** to surface
conversation history"*. There is no export job to build, no pipeline to turn on,
and no ingestion setting to flip. That is why the CES API has no export method
for conversations.

So the question is never "how do I enable it". It is **"which of these is hiding
it"**:

| # | Cause | How it looks |
|---|---|---|
| 1 | Conversation is from the **simulator** | Nothing in Insights, ever, regardless of config |
| 2 | Wrong **location / endpoint** when querying | Everything works; list looks empty |
| 3 | Browser signed into the **wrong Google account** | Console shows "Access Denied" |
| 4 | **`disableConversationLogging: true`** on the app | Nothing in Insights or the Monitor dashboard |
| 5 | Required **APIs** not all enabled | Nothing in Insights |

Causes 1–3 accounted for every false alarm while building this. Cause 4 is the
only actual off-switch, and it is off by default.

---

## Where conversations live when nobody is using Insights

CES keeps its own conversation history regardless of whether anyone looks at
Insights. Nothing is lost while Insights goes unused — the two read the same
Google-managed store.

**Retained by Google, on by default:**

| Where | How to review it |
|---|---|
| CES conversation history | CX Agent Studio → open the agent → agent preview → the conversation history button |
| Monitor dashboard (aggregates) | CX Agent Studio → **Monitor**: total sessions, escalation rate, turns/session, E2E latency, tool failure rate |
| CES API | `GET .../apps/{app}/conversations` and `.../conversations/{id}` |
| CX Insights | The same conversations, with transcript search, sentiment, topics and QA |

Retention follows `conversationLoggingSettings.retentionWindow` — **365 days by
default, 2 years maximum**.

**Customer-owned sinks — these are genuinely off until configured:**

| Sink | Field |
|---|---|
| BigQuery export | `loggingSettings.bigqueryExportSettings` `{enabled, project, dataset}` (plus an `unredacted` variant) |
| Cloud Logging | `loggingSettings.cloudLoggingSettings.enableCloudLogging` |
| Audio recordings in Cloud Storage | `loggingSettings.audioRecordingConfig.gcsBucket` |

Cross-project BigQuery or Cloud Storage needs the CES service agent
`service-<PROJECT_NUMBER>@gcp-sa-ces.iam.gserviceaccount.com` granted
`roles/bigquery.admin` or `storage.objects.create` respectively.

These sinks are a **parallel** path for your own analytics. They are not how
Insights gets its data, and turning them on is not required for Insights.

---

## Order of steps

### 1. Enable the APIs

**If a CES app is already running, the Insights API is already enabled.**
`contactcenterinsights.googleapis.com` is a dependency of `ces.googleapis.com`.
Verified on a project with nothing enabled:

```
$ gcloud services enable ces.googleapis.com     # CES only
$ gcloud services list --enabled
ces.googleapis.com
contactcenterinsights.googleapis.com            <-- pulled in automatically
storage.googleapis.com
bigquerystorage.googleapis.com
```

So "Insights isn't enabled" is almost never the real cause on a project with
live agents. Enable the full set anyway — it is idempotent and covers the
optional features:

```bash
gcloud services enable \
  ces.googleapis.com \
  contactcenterinsights.googleapis.com \
  dialogflow.googleapis.com \
  speech.googleapis.com \
  storage.googleapis.com \
  dlp.googleapis.com \
  --project=PROJECT_ID
```

| API | Needed for |
|---|---|
| `ces` | The agent app itself. Pulls in `contactcenterinsights` + `storage` |
| `contactcenterinsights` | CX Insights. Auto-enabled above |
| `dialogflow` | Dialogflow runtime integration and topic modeling |
| `speech` | Transcribing audio conversations |
| `dlp` | Redaction of transcripts and audio |

A text-only conversation reached Insights in testing without `dialogflow`,
`speech` or `dlp` being enabled at the time of the call — they serve the
features listed, not base chat ingestion.

### 2. Grant the Insights IAM role

**Project Owner is not sufficient** — the console denies a project Owner who has
no explicit Insights role.

```bash
gcloud projects add-iam-policy-binding PROJECT_ID \
  --member=user:SOMEONE@example.com \
  --role=roles/contactcenterinsights.editor
```

`roles/contactcenterinsights.viewer` is enough for read-only access.

Confirm it took effect rather than trusting the console. List the roles actually
bound to the account:

```bash
gcloud projects get-iam-policy PROJECT_ID \
  --flatten="bindings[].members" \
  --filter="bindings.members:user:SOMEONE@example.com" \
  --format="value(bindings.role)"
```

Or check the effective permissions directly — note this is a REST call, there is
no `gcloud projects test-iam-permissions` subcommand:

```bash
curl -s -X POST \
  -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  -H "Content-Type: application/json" \
  "https://cloudresourcemanager.googleapis.com/v1/projects/PROJECT_ID:testIamPermissions" \
  -d '{"permissions":["contactcenterinsights.conversations.list","contactcenterinsights.conversations.get"]}'
```

IAM bindings survive an API being disabled and re-enabled — verified.

### 3. Sign in as the right Google account

If the permissions above are held and the console still says
**"Access Denied — The caller does not have permission"**, the browser is
authenticated as a *different* Google account. This is the single most
time-wasting failure mode, because it is indistinguishable from a real
permissions problem.

- The `authuser=N` index is positional and not stable — bumping it is guesswork.
- The reliable fix is a browser profile (or incognito window) signed in **only**
  as the account holding the role.
- Google is migrating the console to `console.cloud.google` / `auth.cloud.google`
  (no `.com`). Those are genuine Google domains — verified by a Google Trust
  Services certificate for `*.cloud.google` — even though the published
  [required-domains list](https://docs.cloud.google.com/docs/get-started/required-domains)
  still shows only the `.com` forms.

### 4. Confirm the app's logging gates

Both gates are **opt-out** — absent means enabled. A freshly created app already
has conversation logging on.

```bash
curl -s -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  -H "x-goog-user-project: PROJECT_ID" \
  "https://ces.googleapis.com/v1beta/projects/PROJECT_ID/locations/us/apps/APP_ID" \
  | python3 -m json.tool | grep -A4 loggingSettings
```

A default app returns:

```json
"loggingSettings": {
  "conversationLoggingSettings": { "retentionWindow": "31536000s" }
}
```

| Field | Meaning | Required value |
|---|---|---|
| `conversationLoggingSettings.disableConversationLogging` | Console: **"Log your customer conversations"**. Docs: *"applies to both CX Agent Studio and CX Insights"* | `false` / absent |
| `metricAnalysisSettings.llmMetricsOptedOut` | Collection for LLM analysis metrics (sentiment, topics, outcomes) | `false` / absent |

To re-enable if someone turned it off:

```bash
curl -X PATCH -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  -H "Content-Type: application/json" -H "x-goog-user-project: PROJECT_ID" \
  "https://ces.googleapis.com/v1beta/projects/PROJECT_ID/locations/us/apps/APP_ID?updateMask=loggingSettings.conversationLoggingSettings.disableConversationLogging" \
  -d '{"loggingSettings":{"conversationLoggingSettings":{"disableConversationLogging":false}}}'
```

### 5. Send real traffic, not simulator traffic

Every conversation carries a `source`: `LIVE`, `SIMULATOR`, `EVAL` or
`AGENT_TOOL`. **Insights reports on `LIVE` only.** A conversation started from
the CX Agent Studio simulator is recorded as `SIMULATOR` and will never appear,
however the app is configured.

Verified: driving the app through `SessionService.RunSession` over the API yields
`source: LIVE`. Use a deployed channel, a real client, or the API — not the
simulator preview pane.

**A deployment is not required for ingestion.** One verified conversation ran
against the draft app with no deployment at all and still reached Insights. Cut a
deployment because production needs a channel, not to make Insights work.

---

## Verify it worked

### Locations and endpoints — the part that looks broken but isn't

Two rules, and breaking either returns an empty list or a 400 that reads like a
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

Getting this wrong gives:

```
400  Location Mismatch: Server location `global` and
     resource location `us` do not match
```

That error is about the **host**, not the path — the fix is the regional
endpoint, not the IAM policy.

### Confirm by API

```bash
curl -s -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  -H "x-goog-user-project: PROJECT_ID" \
  "https://us-contactcenterinsights.googleapis.com/v1/projects/PROJECT_ID/locations/us/conversations?pageSize=25"
```

A CES conversation appears under the **same id as the CES session**. Observed:

```
dep-b6faf4d340   medium=CHAT  turnCount=3  agentId=insights-demo
  labels: agentRoleType=AUTOMATED_ONLY, sessionContained=true,
          sessionEscalated=false, lastTransferSubAgentNames=Concierge
  transcript: 4 segments (END_USER / AUTOMATED_AGENT), latestAnalysis present
```

Add `?view=FULL` on a single conversation to get the transcript segments.

### Confirm in the console

- `https://ccai.cloud.google.com/insights/projects/PROJECT_ID`
- or CX Agent Studio → your app → **Monitor** → **View Conversations**

Set the console's region selector to the **US multiregion** to match.

### Allow time

A conversation is written only once the **session ends**, and took about **90
seconds** to appear.

---

## Reproducing on another account

```bash
cp .env.example .env     # set GOOGLE_CLOUD_PROJECT, CXAS_LOCATION, INSIGHTS_LOCATION
pip install python-dotenv
gcloud auth login        # as the account holding the Insights role

python bootstrap/deploy_app.py        # app -> agent -> version -> deployment
python verify/run_conversation.py     # 3-turn LIVE conversation, waits for history
python verify/check_insights.py       # all gates + the conversation in Insights
```

`ces_client.py` holds the shared REST helper and derives the regional Insights
endpoint from `INSIGHTS_LOCATION`. Everything uses `gcloud` for the token and
`urllib` for the call — no SDK pinning to get wrong on another machine.

---

## Gotchas hit while building this

None of these are clearly documented:

| Symptom | Cause |
|---|---|
| `CreateApp` fails with bare *"an internal error has occurred"* | `modelSettings.model` is effectively required; `displayName` alone is not enough |
| `The model gemini-2.5-flash is not available in us` | Model must exist in the CES location. `gemini-3.5-flash` works in `us` |
| `User-specified resource ID 'root' must match '[a-zA-Z0-9][a-zA-Z0-9-_]{4,35}'` | All resource IDs must be 5–36 chars. `root` is too short; `concierge` is fine |
| `CreateDeployment` rejects resource ID `'-'` | The documented draft alias `versions/-` is **not** accepted. Cut a real app version and deploy that |
| Sessions fail with no root agent | Creating the agent does not wire it up — `PATCH` the app's `rootAgent` field |
| Create calls appear to hang | App/agent/version/deployment creation are LROs. Agent, version and deployment each took **over 200s** in a cold-start run while still succeeding. Re-read the resource; a poll timeout is not a failure. Budget ~10 min for a full `deploy_app.py` |
| `gcloud projects test-iam-permissions` not found | No such subcommand. Use `get-iam-policy`, or the `:testIamPermissions` REST endpoint |
| `429 RESOURCE_EXHAUSTED` mid-conversation | Default model quota is low on a fresh project. The scripts retry with backoff |
| Conversation missing right after the call | Only written when the **session ends**; ~90s lag |
| `400 Location Mismatch` from Insights | Wrong endpoint host for the location — use the regional prefix |
| Insights list empty at `us-central1` | A CES app in `us` maps to the `us` multiregion, not a region |
| Console "Access Denied" with permissions held | Browser signed into a different Google account |

---

## What was verified

Validated twice: once incrementally, then once as a **full cold start** — all
CES and Insights APIs disabled (`403 SERVICE_DISABLED` on both), every app and
conversation deleted, then this README followed from step 1.

| Step | Result |
|---|---|
| Insights API is a dependency of CES | Yes — enabling `ces` alone pulls in `contactcenterinsights`; disabling `contactcenterinsights` is refused while `ces` is active |
| APIs enable from a fully disabled state | Yes |
| IAM bindings survive API disable/re-enable | Yes |
| app → agent → version → deployment | Yes — rebuilt from scratch by `deploy_app.py` |
| Conversation logging ON by default | Yes — on a freshly created app, both runs |
| API traffic yields `source: LIVE` | Yes — simulator yields `SIMULATOR` |
| Conversation lands in CES history | Yes — ~90s after session end |
| Conversation reaches Insights | **Yes** — cold-start run `verify-20c8d4d69296`, found via the regional endpoint |
| Visible in the CX Insights console | Yes — US multiregion |
| Works without a deployment | Yes — an earlier draft-app conversation had none |

Cold-start evidence: `verify-20c8d4d69296`, `source=LIVE`, `turns=2`,
`deployment=deploy-0001`, present in Insights as `medium=CHAT`,
`agentId=insights-demo`.
