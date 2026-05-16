#!/usr/bin/env bash
# Deploy both Cloud Functions to GCP.
#
# Prerequisites (one-time setup):
#   1. gcloud CLI installed and authenticated: gcloud auth login
#   2. Project created and selected: gcloud config set project <PROJECT_ID>
#   3. Required APIs enabled:
#        gcloud services enable \
#          cloudfunctions.googleapis.com \
#          cloudbuild.googleapis.com \
#          run.googleapis.com \
#          secretmanager.googleapis.com \
#          iam.googleapis.com \
#          artifactregistry.googleapis.com
#   4. Secrets created in Secret Manager:
#        echo -n "<smsoffice-key>" | gcloud secrets create smsoffice-key --data-file=-
#        openssl rand -hex 32 | tr -d '\n' | gcloud secrets create manychat-secret --data-file=-

set -euo pipefail

PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}"
REGION="${REGION:-europe-west1}"
RUNTIME="${RUNTIME:-python312}"
SENDER="${SMSOFFICE_SENDER:-BitCamp}"
MAX_INSTANCES="${MAX_INSTANCES:-5}"
SEND_SMS_SA_NAME="${SEND_SMS_SA_NAME:-send-sms-runtime}"
CALLBACK_SA_NAME="${CALLBACK_SA_NAME:-sms-callback-runtime}"
SEND_SMS_SA="${SEND_SMS_SA:-${SEND_SMS_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com}"
CALLBACK_SA="${CALLBACK_SA:-${CALLBACK_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com}"

if [[ -z "$PROJECT_ID" || "$PROJECT_ID" == "(unset)" ]]; then
  echo "PROJECT_ID is not set. Run: gcloud config set project <PROJECT_ID>" >&2
  exit 1
fi

ensure_service_account() {
  local name="$1"
  local email="$2"
  local description="$3"

  if ! gcloud iam service-accounts describe "$email" --project="$PROJECT_ID" >/dev/null 2>&1; then
    gcloud iam service-accounts create "$name" \
      --project="$PROJECT_ID" \
      --display-name="$description"
  fi
}

ensure_service_account "$SEND_SMS_SA_NAME" "$SEND_SMS_SA" "Runtime identity for send-sms"
ensure_service_account "$CALLBACK_SA_NAME" "$CALLBACK_SA" "Runtime identity for sms-callback"

for s in smsoffice-key manychat-secret; do
  gcloud secrets add-iam-policy-binding "$s" \
    --project="$PROJECT_ID" \
    --member="serviceAccount:${SEND_SMS_SA}" \
    --role="roles/secretmanager.secretAccessor" \
    --quiet >/dev/null
done

echo "Deploying send-sms..."
gcloud functions deploy send-sms \
  --gen2 \
  --runtime="$RUNTIME" \
  --project="$PROJECT_ID" \
  --region="$REGION" \
  --source=. \
  --entry-point=send_sms \
  --trigger-http \
  --allow-unauthenticated \
  --service-account="$SEND_SMS_SA" \
  --memory=256Mi \
  --max-instances="$MAX_INSTANCES" \
  --clear-min-instances \
  --timeout=15s \
  --set-env-vars="SMSOFFICE_SENDER=$SENDER" \
  --set-secrets="SMSOFFICE_API_KEY=smsoffice-key:latest,MANYCHAT_SHARED_SECRET=manychat-secret:latest"

echo ""
echo "Deploying sms-callback..."
gcloud functions deploy sms-callback \
  --gen2 \
  --runtime="$RUNTIME" \
  --project="$PROJECT_ID" \
  --region="$REGION" \
  --source=. \
  --entry-point=sms_callback \
  --trigger-http \
  --allow-unauthenticated \
  --service-account="$CALLBACK_SA" \
  --memory=256Mi \
  --max-instances="$MAX_INSTANCES" \
  --clear-min-instances \
  --timeout=10s \
  --clear-env-vars \
  --clear-secrets

echo ""
echo "Done. URLs:"
gcloud functions describe send-sms --project="$PROJECT_ID" --region="$REGION" --gen2 --format='value(serviceConfig.uri)'
gcloud functions describe sms-callback --project="$PROJECT_ID" --region="$REGION" --gen2 --format='value(serviceConfig.uri)'
