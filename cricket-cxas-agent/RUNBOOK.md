# Runbook: deploy the Cricket Care troubleshooting agent into a new project

Everything project-specific lives in `.env`. Pointing the bundle at another Google Cloud
project is a config change plus the commands below. Budget about an hour the first time, most of it
waiting on the server build and the tests.

The agent itself is the folder `app/`, in the SCRAPI (`cxas-scrapi`) app format: one folder per agent
with its `instruction.txt` and callbacks, plus the tools, the support toolset and the variables.
`deploy.sh` pushes it with `cxas push`.

One app answers phone calls and web chat. It runs on the `gemini-composite-v2` model, which takes
spoken and typed turns. On each turn the app reads how the turn arrived: a spoken turn gets voice
wording, a typed turn gets chat wording plus a picture of the step and quick replies.
Run every command from the `cricket-cxas-agent/` folder.

## 0. What you need

| Item | Notes |
|---|---|
| A Google Cloud project with billing enabled | Owner, or these roles: Customer Engagement Suite admin, Cloud Run admin, Cloud Build editor, Service Usage admin, Project IAM admin, Storage admin. |
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
project per region per base model**, the row for the app's model (`gemini-composite-v2`).

| Value | What to expect |
|---|---|
| 10,000 or more | Comfortable for one conversation at a time. |
| 1,000 (the default) | Most turns get rate-limited. One turn uses about 4,000 tokens, so only one turn every 4 minutes fits: set `TURN_TESTS_RPM=0.25` and expect the tests to take about 2.5 hours. Request an increase. |

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
| `CARE_APP_ID`, `DEMO_CUSTOMER_ID`, `SUPPORT_MCP_SERVICE`, `DEMO_PROFILE` | keep the example values |
| `DATASTORE_ID`, `FIRESTORE_DATABASE`, `FIRESTORE_LOCATION`, `RESUME_WINDOW_MINUTES`, `EXTRACT_MODEL` | keep the example values |
| `IMAGES_BUCKET`, `IMAGE_LINK_MINUTES` | optional. The private bucket for step pictures (default `<project>-cricket-tutorial-images`) and how long a picture link in chat stays valid (default 60 minutes) |
| `CHAT_WEB_SERVICE`, `CHAT_DEPLOYMENT_ID`, `CHAT_TITLE`, `CHAT_EXTRA_ORIGINS` | optional, for web chat (step 7). The defaults work |
| `TURN_TESTS_RPM` | requests per minute for the tests: `6` with a raised quota, `0.25` at the default 1,000 tokens per minute |
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM`, `DEMO_SMS_NUMBER` | optional. Fill all four to have the agent text the guide link to `DEMO_SMS_NUMBER` (a Twilio trial only sends to numbers verified in Twilio). Leave empty and the agent says it could not text and reads the link instead. |

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pytest -q
```

Expect `75 passed`. A warning about ffmpeg is harmless.

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
| Pictures | Creates the private bucket if missing and copies each step's picture into it. Only new pictures are copied; the first run copies about 2,900 and takes 20 to 30 minutes. A few may fail on a timeout: rerun to pick them up. A step without a picture still works in chat, without one |
| Load | Upserts one document per tutorial into the data store and removes tutorials that are gone. Search sees changes within a few minutes |

Rerun this whenever tutorials change. The agent needs no redeploy for new content.

## 5. Deploy and test

```bash
deploy/deploy.sh             # server, app, then the tests
deploy/deploy.sh --no-test   # deploy only
```

| Step | What it does |
|---|---|
| Support server | Builds and deploys the private Cloud Run service `cricket-support-mcp` (one always-warm instance). Takes 3 to 5 minutes |
| Access | Lets the server use Firestore, sign picture links and read the picture bucket, and lets the agent platform call the server |
| Build | Copies `app/` to a temporary folder and fills in the two per-project values: the server's URL in `toolsets/support/support.json`, and the data store in `environment.json`. Then runs `cxas lint` on it |
| Create | Creates app `cricket-care` with the model from `app/app.json` if it does not exist |
| Push | `cxas push --overwrite` makes the live app match `app/` exactly, removing anything that is no longer in the folder |
| Tests | Runs `bootstrap/run_turn_tests.py` |

### Tests

The scenarios are in `turn_tests/scenarios.yaml`, in SCRAPI's turn test format. Each is a scripted
caller, with checks after each turn (which tools were called, with which arguments, and words the
agent must say) and plain-language checks on the whole conversation, graded by Gemini. They run
from your machine against the deployed app; nothing is added to the app.

```bash
.venv/bin/python bootstrap/run_turn_tests.py           # every scenario
.venv/bin/python bootstrap/run_turn_tests.py P1 P3     # only these profiles
```

Scenarios run one at a time, in file order. Each is tagged with the demo profile it needs, and the
runner resets the demo account to that profile before it, which also clears any saved place. The
callback scenario is tagged `continues`: it skips the reset and resumes the place the drop scenario
above it saved. A scenario stops at its first failed turn.

It prints PASS or FAIL per scenario and writes `runs/<UTC timestamp>/results.csv`: one row per check,
with what was expected, what happened, and the session id to look up in the console.

The scenarios send typed turns, so the app answers them as chat. A check on exact words written for
a phone call can fail on chat wording; the tool checks apply to both.

To put the demo account in a given state for manual testing: `.venv/bin/python bootstrap/demo_reset.py P1`.

### Change the agent

Edit the files in `app/` (an instruction, a callback, the step tool), then:

```bash
.venv/bin/cxas lint --app-dir app     # must pass before deploying
deploy/deploy.sh --no-test
```

To see exactly what is live, pull it: `.venv/bin/cxas pull projects/<project>/locations/us/apps/cricket-care --target-dir /tmp/live`.
Edits made in the console are overwritten by the next deploy; copy them into `app/` first.

## 6. Voice

1. Console → Customer Engagement Suite → the `cricket-care` app.
2. Create a version, then a deployment from it. If a deployment already exists from an earlier
   deploy, create a new version and point the deployment at it: a deployment keeps serving its old
   version until then.
3. In the telephony settings, bind a phone number to that deployment.
4. Pick a profile (below), then call the number.
5. Note the conversation id shown in the console for each call, and anything that sounded
   wrong (reading long lists, talking over you, long silences).

Console menu names may differ slightly from the above; the order of the steps does not.

### The demo account

Every call is the same signed-in customer, Jordan Reyes (`cust_2001`); the number you call from
is not used. The account has two phones, in every profile:

| Line | Phone | Note |
|---|---|---|
| L1 | iPhone 13 | The line you are "calling from"; the agent assumes it first |
| L2 | Galaxy A15 5G | Say "it's my Galaxy" or "the second line" to switch |

The agent only gives steps for these two phones. Tutorials exist for four phones: these two,
Moto G 2025 and Moto G Stylus 5G (2024).

### Switch the profile before a call

The profile sets the account's state. Switch it from this folder, then call:

```bash
.venv/bin/python bootstrap/demo_reset.py P1
```

It prints the account state, for example `{"profile": "P1", ... "lines": {"L1": "SUSPENDED_NONPAY", ...}}`.

- It takes effect on the next call. No redeploy.
- It also clears any saved place, so the next call does not resume a dropped one. Run it with
  the same profile to start fresh.
- It lasts until the next reset or until the server restarts. On restart the account returns to
  `DEMO_PROFILE` in `.env` (P3 unless changed; change it and run `deploy/deploy.sh --no-test`).
- A test run resets the account back to `DEMO_PROFILE` when it finishes.

### What to test in each profile

| Profile | Account state | Say | Expect |
|---|---|---|---|
| P1 | iPhone line suspended, payment past due | "my calls keep failing", then "yes" | The agent finds the suspension and offers billing. No device steps |
| P2 | Network outage at the account's zip | "I have no service at all", then "yes" | It reports the outage and when it should be fixed, and says the phone is fine. No device steps |
| P3 | Clean | "my wifi is really slow", then "yes", then "walk me through it" | It checks the account, finds the Wi-Fi guide for the iPhone, offers text, walk-through or both, then gives one step at a time. Say "done" or "next" after each |
| P3 | Clean | "my Galaxy won't turn on" | It switches to the Galaxy and finds a Galaxy guide, not an iPhone one |
| P3 | Clean | "my bluetooth won't pair, just text me the guide" | It finds the guide and texts the link. Without Twilio in `.env` it says it couldn't send and offers to walk you through it |
| P3 | Clean | "my Pixel screen is frozen" | It says the Pixel is not on the account and asks you to read the model from Settings. No steps |
| P3 | Clean | Wi-Fi walk-through until the restart step | It warns the step will end the call and asks you to confirm. Say yes, hang up, call back within 30 minutes and say "I'm calling back": it welcomes you back and asks whether the restart fixed it |
| P7 | iPhone used all its high-speed data, slowed until the cycle ends | "data is crawling on my iPhone", then "yes" | It explains the data is used up and when speed returns, then offers device steps anyway. Say "still slow" a few times: it opens a ticket |

P4, P5 and P6 are clean accounts, the same as P3.

## 7. Web chat

```bash
deploy/chat.sh
```

Run it after `deploy/deploy.sh`, and again after every later deploy: the chat channel serves a
version of the app, and this creates a new one. Safe to rerun.

| Step | What it does |
|---|---|
| Demo page | Deploys `chat_web/` as the public Cloud Run service `cricket-chat-web`: a copy of the Cricket support page with the chat widget on it |
| Version | Creates a version of the app as it is now |
| Chat channel | Creates the chat-only deployment `cricket-chat` if missing and points it at the new version. Public access is on, allowed only from the demo page's own address (plus `CHAT_EXTRA_ORIGINS`) |

It prints the chat page's address at the end. Open it, then open the chat from the mascot's
**Start chat** button or the chat button at the bottom right.

- The agent greets when the chat opens: "Welcome to Cricket Wireless, Jordan. How can I help you today?"
  The name is the app variable `customer_name`; the page shows `CHAT_USER` as the signed-in customer.
- The chat window uses the browser's height, and each step picture is sized to show whole. Use a
  maximised window.

- Chat uses the same demo account and profile as voice. Switch profiles the same way.
- In chat the agent never texts the guide; it puts the link in its reply.
- Each walk-through step shows its picture and three quick replies: Done, Say it again, I'm stuck.
- The page keeps the conversation across reloads. Open it in a private window for a clean start.
- The pictures stay private. The agent hands the page links that expire after `IMAGE_LINK_MINUTES`.

## 8. Demo scripts

Two scenarios, one per channel, both on the same app and the same account. Both were run end to end
against the deployed app: the voice one with spoken turns, the chat one on the chat page.

Before each one, reset the account. It clears any saved place, which otherwise makes the agent open
with "Welcome back":

```bash
.venv/bin/python bootstrap/demo_reset.py P3
```

Leave a few seconds between turns. At the default quota a fast run hits the rate limit: on a call
the line drops, in chat the page shows an error with a Retry button. Check the quota (step 1) on the
project you demo from.

### Voice: slow Wi-Fi, the call drops, the caller rings back

Shows: account checks before device steps, one step at a time, a warning before a step that ends the
call, and picking up where the caller left off.

| # | Say | The agent |
|---|---|---|
| 1 | "My Wi-Fi is really slow" | Says it sees you are calling from your iPhone and asks if that is the one |
| 2 | "Yes, it's this iPhone" | Says everything looks normal on its side, names the guide for Wi-Fi connection issues or slowdowns, offers to text it, walk you through it, or both |
| 3 | "Walk me through it" | Step 1: open Settings and tap Wi-Fi |
| 4 | "Done" | Step 2: Cellular, Wi-Fi Assist |
| 5 | "Done" | Warns that the next step will disconnect the call, says it saved your place, asks you to confirm you are okay to call back |
| 6 | "Done" (optional) | Does not accept it: asks again for a clear confirmation |
| 7 | "Yes, I'm okay to call back" | Tells you to restart the iPhone and call back |
| 8 | Hang up. Call again within 30 minutes: "Hi, my call dropped while I was restarting my phone" | "Welcome back, I saved your place." Asks whether the restart fixed it |

End the demo at row 8. The step after the restart also ends the call, so answering "no, it's still
slow" brings the same warning again.

### Chat: set up Wi-Fi calling, with a picture of every step

Shows: the same agent in chat wording, a picture of the screen under every step, and quick replies.
Open the chat page from step 7 in a private window.

| # | Type or click | The agent |
|---|---|---|
| 1 | "How do I set up Wi-Fi calling on my iPhone?" | Says it sees you are chatting from your iPhone and asks if that is the one |
| 2 | "Yes" | Names the guide Activating Wi-Fi calling, offers the link, a walk-through here, or both |
| 3 | "Walk me through it here" | Step 1 with a picture of the Settings screen, and the quick replies Done, Say it again, I'm stuck |
| 4 | Click **Done** | Step 2 with its picture |
| 5 | Click **Done** for each of the 6 steps | A picture under every step. No step in this guide ends a call |
| 6 | Optional: click **Say it again** or **I'm stuck** on any step | Repeats the step, or helps with it |

## How a call works

| Part | Where it runs | Role |
|---|---|---|
| `search_tutorials` | Agent platform, data store tool | Finds tutorials for the caller's words, filtered to their phone |
| `before_agent_callbacks/` (both agents) | Agent platform, callback | Sets `channel` to voice or chat from how the turn arrived |
| `app/agents/Tech_Support/after_tool_callbacks/` | Agent platform, callback | Drops results for other phones, keeps the steps out of the model's view, loads a saved place on callback. In chat, notes the step's picture |
| `app/agents/Tech_Support/after_model_callbacks/` | Agent platform, callback | Chat only: attaches the step's picture and the quick replies under the reply |
| `sign_images` | Support server | Chat only: makes short-lived links to a guide's pictures in the private bucket |
| `app/tools/next_step/` | Agent platform, Python tool | Gives one step at a time. Holds a step that ends the call until the caller says yes, and any step that ends or might drop the call until its place is saved |
| `app/agents/Tech_Support/before_tool_callbacks/` | Agent platform, callback | Fills `save_progress` with the caller's place, so the model never copies it |
| `get_progress`, `save_progress` | Support server | Keep the caller's place in Firestore `progress/{customer_id}`, used once within `RESUME_WINDOW_MINUTES` |
| Account tools, `send_guide_link`, `open_ticket` | Support server | Demo account checks and outreach |

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `cxas push` or the create step fails with permission denied | The application-default login is a different user, or lacks the platform admin role | Rerun `gcloud auth application-default login` as the project user |
| Any API error mentioning a quota project | Quota project not set for application default credentials | `gcloud auth application-default set-quota-project "$PROJECT"` |
| `deploy.sh` fails at the build | Cloud Build service account lacks permissions, common in managed orgs | Ask the org admin for the default Cloud Build setup, or grant the build service account Cloud Run and Artifact Registry roles |
| `deploy.sh` fails granting the invoker role on `gcp-sa-ces` | An org policy limits which identities can be granted roles | Ask the org admin to allow Google-managed service agents |
| `content.sh` stops with "steps are … bytes encoded" | A tutorial is too large for the search tool, which silently drops results of about 16 KB | Split the tutorial, or raise the limit in `knowledge/load_datastore.py` only after testing it |
| The build prints "review entry no longer matches the step text" | A scraped tutorial changed under a hand-reviewed step | Recheck that step and update `knowledge/step_review.json` |
| Tests fail with `429 Resource has been exhausted` | Token quota at the default | Set `TURN_TESTS_RPM=0.25`, or raise the quota (step 1) |
| `deploy.sh` stops at `cxas lint` | An edit in `app/` breaks a SCRAPI rule | Fix what the lint names; `cxas lint --app-dir app` shows the same list |
| The chat page shows "An unexpected error occurred" | Rate limit on the token quota (the request returns 429) | Wait a minute and press Retry, or raise the quota (step 1) |
| The chat page fails on the first message every time | The page's address is not in the channel's allowed list, or `chat.sh` has not run since the app was recreated | Rerun `deploy/chat.sh` |
| Chat steps show no picture | The picture copy has not run, or the server cannot read the bucket | Run `deploy/content.sh`, then `deploy/deploy.sh --no-test` |
| `chat.sh` fails at the demo page | An org policy blocks public Cloud Run services | Ask the org admin to allow it for this service, or serve `chat_web/` elsewhere and add that address to `CHAT_EXTRA_ORIGINS` |
| The agent says it found nothing for a common problem right after `content.sh` | The data store is still indexing | Wait a few minutes |

## Known behaviour

- One turn uses about 4,000 tokens. The test runner does not retry a rate-limited turn; it paces
  requests at `TURN_TESTS_RPM` instead.
- `next_step` must stay the first function in its file: the platform takes the first one as the tool.
- Set `MCP_WIRE_LOG=1` in `.env` and redeploy to log every request to the server. Useful for
  debugging tool calls; noisy otherwise.

## Tear down

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
