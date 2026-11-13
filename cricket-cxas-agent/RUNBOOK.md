# Runbook: deploy the Cricket Care troubleshooting agent and run the demo

One app answers phone calls and web chat, on the `gemini-composite-v2` model. A spoken turn gets
voice wording; a typed turn gets chat wording, a picture of the step and quick replies.
Everything project-specific lives in `.env`. Run every command from the `cricket-cxas-agent/` folder.

## 1. What you need

| Item | Notes |
|---|---|
| A Google Cloud project with billing enabled | Owner, or these roles: Customer Engagement Suite admin, Cloud Run admin, Cloud Build editor, Service Usage admin, Project IAM admin, Storage admin |
| `gcloud` CLI and Python 3.10 or newer | |
| This repository | `git clone https://github.com/puvvula89/att-voice.git && cd att-voice/cricket-cxas-agent` |
| Quota | Console → IAM & Admin → Quotas & System Limits → **Gemini Enterprise for Customer Experience API** → **RunSession LLM tokens per minute per project per region per base model**, the `gemini-composite-v2` row. 10,000 or more is comfortable; at the default 1,000 most turns are rate-limited |

## 2. Log in and configure

```bash
PROJECT=<your-project-id>
gcloud auth login
gcloud auth application-default login
gcloud config set project "$PROJECT"
gcloud auth application-default set-quota-project "$PROJECT"

cp .env.example .env          # set GOOGLE_CLOUD_PROJECT; keep the other example values
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pytest -q           # expect all tests to pass
```

Optional in `.env`: the four `TWILIO_*`/`DEMO_SMS_NUMBER` values let the agent text the guide link;
without them it says it could not text. `CHAT_USER` is the name shown as signed in on the chat page.

## 3. Deploy

Run these in order. Each is safe to rerun.

| # | Command | What it does | Time |
|---|---|---|---|
| 1 | `deploy/prep.sh` | Enables the APIs, creates the Firestore database and the Agent Search data store `cricket-tutorials` if missing | 2 min |
| 2 | `deploy/content.sh` | Builds the tutorial catalog from the tutorials in the repository (no scraping), copies the step pictures into a private bucket, loads the data store | 20 to 30 min, mostly pictures |
| 3 | `deploy/deploy.sh --no-test` | Deploys the support server to Cloud Run and pushes the agent app `cricket-care` | 5 min |
| 4 | `deploy/chat.sh` | Deploys the chat page to Cloud Run, creates an app version and the public chat channel on it, prints the chat page's address | 2 min |

Notes:

- **Existing data store:** keep its id in `DATASTORE_ID`; step 2 reloads it. Search sees the reload
  within a few minutes, so carry on with steps 3 and 4 meanwhile.
- **Existing app from an older build:** the app's model is set when the app is created. If
  `cricket-care` already exists on another model, delete it (or run `deploy/teardown.sh`) before step 3.
- **Pictures:** a few copies may time out; rerun step 2 to pick them up.
- **After any later change to `app/`:** rerun steps 3 and 4.

### Updating a project that is already set up

Use this when the project already has the data store (and perhaps an older deploy). Nothing is
scraped: the tutorials, including the iPhone 18 Pro, are in the repository.

```bash
git checkout main && git pull
grep -E "GOOGLE_CLOUD_PROJECT|DATASTORE_ID" .env    # must be this project and the existing data store's id
deploy/prep.sh                 # enables two more APIs, updates the Python packages; keeps the data store
deploy/content.sh              # copies the step pictures into a new private bucket, reloads the data store (20 to 30 min)
deploy/deploy.sh --no-test     # support server and agent app
deploy/chat.sh                 # chat page and chat channel; prints the page address
.venv/bin/python bootstrap/demo_reset.py P3
```

Then point the phone deployment at a new version (section 4).

Two checks:

- If `deploy/content.sh` ends with `failed` pictures, run it again; it copies only the missing ones.
- If the app `cricket-care` already exists in the project from a build before web chat, it is on a
  voice-only model that cannot be changed. Delete it before `deploy/deploy.sh`, then recreate the
  phone deployment afterwards:

  ```bash
  .venv/bin/cxas --no-input delete --app-name "projects/<project-id>/locations/us/apps/cricket-care" --force
  ```

## 4. Phone number

1. Console → Customer Engagement Suite → the `cricket-care` app.
2. Create a version, then a deployment from it. If a deployment already exists, point it at a new
   version: a deployment keeps serving its old version until then.
3. In the telephony settings, bind a phone number to that deployment.

## 5. The demo account

Every call and chat is the same signed-in customer, Jordan (`cust_2001`), with two phones: an
iPhone 18 Pro (the line they contact us from) and a Galaxy A15 5G.

Reset the account before each scenario. It clears any saved place, which otherwise makes the agent
open with "Welcome back":

```bash
.venv/bin/python bootstrap/demo_reset.py P3
```

## 6. Demo scripts

Two scenarios, one per channel, on the same app and the same account. Both were run end to end
against the deployed app: the voice one with spoken turns, the chat one on the chat page.
Reset the account (section 5) before each.

### Voice: Wi-Fi calling isn't working, a frustrated caller, the call drops, the caller rings back

Shows: account checks before device steps, natural spoken guidance one step at a time, empathy when
the caller gets frustrated, a warning before a step that ends the call, and picking up where the
caller left off.

| # | Say | The agent |
|---|---|---|
| 1 | "Wi-Fi calling isn't working on my phone" | Says it sees you are calling from your iPhone 18 Pro and asks if that is the one |
| 2 | "Yes, this iPhone" | Says everything looks normal on its side, names the guide Wi-Fi Calling isn't working, offers to text it, walk you through it, or both |
| 3 | "Walk me through it" | Says what the guide covers and asks you to say when you are ready |
| 4 | "I'm ready" | Settings, Apps, Phone: asks whether Wi-Fi Calling is turned on |
| 5 | "Where the hell is that? I can't find Wi-Fi calling anywhere, this is so frustrating" | Apologises, says it is not your fault, and guides you there in smaller moves; asks what you see |
| 6 | "Okay, I found it, it's turned on" | Next step: Cellular, turn off Wi-Fi Assist |
| 7 | "Done" | Next step: General, Software Update |
| 8 | "Done" | Warns that the next step will disconnect the call, says it saved your place, asks whether you are okay to hang up and call back |
| 9 | "Sorry, I did not understand what you said" (optional) | Explains again in simpler words: the step is a restart, it ends the call, your place is saved |
| 10 | "Ok" | Tells you how to restart the iPhone and to call back |
| 11 | Hang up. Call again within 30 minutes: "Hi, I called a few minutes ago about Wi-Fi calling" | "Welcome back, I saved your place." Asks whether the restart fixed it |
| 12 | "No, it still isn't working" | Next step: try a different Wi-Fi network or turn off a VPN |

End the demo at row 12. The step after it resets network settings, which also ends the call, so
"Done" brings the same warning again. The frustrated line in row 5 works on any step.

### Chat: delete and restore a voicemail, with a picture of every step

Shows: the same agent in chat wording, a 13-step guide for the iPhone 18 Pro with a picture of the
screen under every step, quick replies, and the same empathy in writing. Open the chat page in a
private window and maximise it.

| # | Type or click | The agent |
|---|---|---|
| 1 | Open the chat: the mascot's **Start chat** button or the chat button at the bottom right | "Welcome to Cricket Wireless, Jordan. How can I help you today?" |
| 2 | "How do I delete a voicemail on my iPhone?" | Says it sees you are chatting from your iPhone 18 Pro and asks if that is the one |
| 3 | "Yes" | Names the guide Deleting and restoring voicemails, offers the link, a walk-through here, or both |
| 4 | "Walk me through it here" | Step 1 with a picture of the screen, and the quick replies Done, Say it again, I'm stuck |
| 5 | Click **Done** | Step 2 with its picture |
| 6 | "Where the hell is the menu icon? I can't see it anywhere" | Apologises and explains where to look, in different words |
| 7 | Click **Done** for each remaining step | A picture under every step, through deleting, restoring and clearing voicemails. No step in this guide ends a call |

## 7. Tear down

```bash
deploy/teardown.sh           # asks first; --yes skips the question
```

Deletes the app (with its chat channel), both Cloud Run services, the picture bucket, the data
store, and the saved progress. It keeps the
enabled APIs and the Firestore database itself (deleting a project's `(default)` database blocks
re-creating it for a while). The server images stay in the Artifact Registry repository
`cloud-run-source-deploy`; delete it with
`gcloud artifacts repositories delete cloud-run-source-deploy --location us-central1` if no other
Cloud Run service in the project was deployed from source.
