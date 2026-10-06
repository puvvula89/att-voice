# CES conversations into CX Insights

## How ingestion works

```
   caller / client
         |
         v
  +----------------+
  |    CES app     |   conversation runs, source = LIVE
  +----------------+
         |
         |  logged automatically
         |  (off only if disableConversationLogging = true)
         v
  +--------------------------+
  | Google-managed storage   |   shared - no export, no pipeline
  +--------------------------+
         |                  |
         v                  v
  CX Agent Studio       CX Insights
  conversation          console
  history
```

Nothing to turn on. Enable the APIs, grant the role, look in the right region.

## 1. Enable the APIs

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

## 2. Grant access

```bash
gcloud projects add-iam-policy-binding PROJECT_ID \
  --member=user:someone@example.com \
  --role=roles/contactcenterinsights.viewer
```

Project Owner is not enough.

## 3. View

```
https://ccai.cloud.google.com/insights/projects/PROJECT_ID
```

Set the region selector to the **US multiregion**.

---

## Test in a new project

```bash
cp .env.example .env          # set GOOGLE_CLOUD_PROJECT
gcloud auth login
python bootstrap/deploy_app.py        # builds the app   (~10 min)
python verify/run_conversation.py     # runs a LIVE conversation
python verify/check_insights.py       # confirms it reached Insights
```

Success looks like:

```
verify-20c8d4d69296  source=LIVE  turns=2
verify-20c8d4d69296: FOUND in Insights
```

Tear down:

```bash
curl -X DELETE -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  -H "x-goog-user-project: PROJECT_ID" \
  "https://ces.googleapis.com/v1beta/projects/PROJECT_ID/locations/us/apps/insights-demo?force=true"
```

## If nothing appears

- Simulator conversations never reach Insights. Only `source: LIVE` does.
- `disableConversationLogging: true` on the app stops all logging.
- "Access Denied" with the role granted means the browser is on a different Google account.
- Conversations are written when the session ends, after ~90 seconds.
