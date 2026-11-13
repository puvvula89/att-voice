#!/usr/bin/env bash
# Stage 4 (optional): web chat. Deploys the demo page on Cloud Run and creates the chat widget channel
# on the agent app, open to the public but only from that page's address. Safe to re-run.
#
#   deploy/chat.sh
#
# Run deploy/deploy.sh first: the channel serves a new version of the app as it is now.
. "$(dirname "$0")/common.sh"
APP_ID="${CARE_APP_ID:-cricket-care}"
LOC="${CXAS_LOCATION:-us}"
APP="projects/${PROJECT}/locations/${LOC}/apps/${APP_ID}"
CHAT_SERVICE="${CHAT_WEB_SERVICE:-cricket-chat-web}"
CHAT_DEPLOYMENT_ID="${CHAT_DEPLOYMENT_ID:-cricket-chat}"

step "Demo page $CHAT_SERVICE in $REGION"
gcloud run deploy "$CHAT_SERVICE" \
  --source chat_web --region "$REGION" --project "$PROJECT" \
  --allow-unauthenticated --max-instances 2 \
  --set-env-vars "^|^CHAT_DEPLOYMENT=${APP}/deployments/${CHAT_DEPLOYMENT_ID}|CHAT_TITLE=${CHAT_TITLE:-Cricket Chat}|CHAT_USER=${CHAT_USER:-Jordan}" \
  --quiet >/dev/null
# A service has two addresses; the widget is allowed from both.
ORIGINS=$(gcloud run services describe "$CHAT_SERVICE" --region "$REGION" --project "$PROJECT" \
            --format='value(status.url,metadata.annotations."run.googleapis.com/urls")')

step "Chat channel $CHAT_DEPLOYMENT_ID on $APP_ID: chat only, public, allowed only from the demo page"
$PY - "$APP" "$CHAT_DEPLOYMENT_ID" "${CHAT_TITLE:-Cricket Chat}" "$ORIGINS" "${CHAT_EXTRA_ORIGINS:-}" <<'PY'
import re, sys, time
import google.cloud.ces_v1beta.types as T
from cxas_scrapi.core.deployments import Deployments
from cxas_scrapi.core.versions import Versions

app, dep_id, title, found, extra = sys.argv[1:]
origins = sorted(set(re.findall(r"https?://[^\s\"',\]\[;]+", found + " " + extra)))
version = Versions(app_name=app).create_version(display_name=f"chat {time.strftime('%Y-%m-%d %H:%M')}")
deployments = Deployments(app_name=app)
if not any(d.name.endswith(f"/deployments/{dep_id}") for d in deployments.list_deployments()):
    deployments.create_deployment(dep_id, "Web chat", version.name, channel_type="WEB_UI",
                                  modality="CHAT_ONLY", theme="LIGHT", web_widget_title=title)
WW = T.ChannelProfile.WebWidgetConfig
profile = T.ChannelProfile(
    channel_type=T.ChannelProfile.ChannelType.WEB_UI,
    web_widget_config=WW(modality=WW.Modality.CHAT_ONLY, theme=WW.Theme.LIGHT, web_widget_title=title,
                         security_settings=WW.SecuritySettings(
                             enable_public_access=True, enable_origin_check=True, allowed_origins=origins)))
deployments.update_deployment(dep_id, app_version=version.name, channel_profile=profile)
print("version", version.name.split("/")[-1], "| allowed from:", ", ".join(origins))
PY

echo; echo "chat page: $(echo "$ORIGINS" | tr '\t;' '\n\n' | grep -o 'https://[^" ,]*' | head -1)"
