# CES conversations into CX Insights

CES and CX Insights share the same storage, so ingestion is native and on by
default. There is no export job and no ingestion setting. You only need the APIs
and the right permission.

```bash
PROJECT=your-project     # GCP project
LOC=us                   # CES app location: us, eu or global
TOKEN=$(gcloud auth print-access-token)
```

## 1. Enable the APIs

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

`contactcenterinsights` is a dependency of `ces`, so it is already enabled on any
project running agents. `dialogflow` is for runtime integration, `speech` for
audio transcription, `dlp` for redaction.

## 2. Grant permission

Project Owner is **not** enough — the role must be granted explicitly.

```bash
gcloud projects add-iam-policy-binding $PROJECT \
  --member=user:someone@example.com \
  --role=roles/contactcenterinsights.viewer
```

Use `roles/contactcenterinsights.editor` for write access.

## 3. View the conversations

Console — set the region selector to the **US multiregion**:

```
https://ccai.cloud.google.com/insights/projects/PROJECT_ID
```

Or CX Agent Studio → your app → **Monitor** → **View Conversations**.

By API — the endpoint host prefix must match the location:

```bash
curl -s -H "Authorization: Bearer $TOKEN" -H "x-goog-user-project: $PROJECT" \
  "https://$LOC-contactcenterinsights.googleapis.com/v1/projects/$PROJECT/locations/$LOC/conversations?pageSize=5"
```

| CES location | Endpoint |
|---|---|
| `us` | `https://us-contactcenterinsights.googleapis.com` |
| `eu` | `https://eu-contactcenterinsights.googleapis.com` |
| `global` | `https://contactcenterinsights.googleapis.com` |

## If nothing appears

- **Simulator traffic never appears.** Only `source: LIVE` is reported on.
- **Check the opt-out**: `disableConversationLogging: true` on the app stops all
  logging. Absent means it is on.
- **"Access Denied" with the role granted** means the browser is signed in as a
  different Google account.
- Conversations are written when the session **ends**, after roughly 90 seconds.

`python verify/check_insights.py` reports all of the above for one app.
