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
#          artifactregistry.googleapis.com
#   4. Secrets created in Secret Manager:
#        echo -n "<smsoffice-key>" | gcloud secrets create smsoffice-key --data-file=-
#        openssl rand -hex 32 | tr -d '\n' | gcloud secrets create manychat-secret --data-file=-
#   5. The compute default service account has access to the secrets:
#        PROJECT_NUMBER=$(gcloud projects describe $(gcloud config get-value project) --format='value(projectNumber)')
#        for s in smsoffice-key manychat-secret; do
#          gcloud secrets add-iam-policy-binding $s \
#            --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
#            --role="roles/secretmanager.secretAccessor"
#        done

set -euo pipefail

REGION="${REGION:-europe-west1}"
RUNTIME="${RUNTIME:-python312}"
SENDER="${SMSOFFICE_SENDER:-BitCamp}"

echo "Deploying send-sms..."
gcloud functions deploy send-sms \
  --gen2 \
  --runtime="$RUNTIME" \
  --region="$REGION" \
  --source=. \
  --entry-point=send_sms \
  --trigger-http \
  --allow-unauthenticated \
  --memory=256Mi \
  --timeout=15s \
  --set-env-vars="SMSOFFICE_SENDER=$SENDER" \
  --set-secrets="SMSOFFICE_API_KEY=smsoffice-key:latest,MANYCHAT_SHARED_SECRET=manychat-secret:latest"

echo ""
echo "Deploying sms-callback..."
gcloud functions deploy sms-callback \
  --gen2 \
  --runtime="$RUNTIME" \
  --region="$REGION" \
  --source=. \
  --entry-point=sms_callback \
  --trigger-http \
  --allow-unauthenticated \
  --memory=256Mi \
  --timeout=10s \
  --set-env-vars="SMSOFFICE_SENDER=$SENDER" \
  --set-secrets="SMSOFFICE_API_KEY=smsoffice-key:latest,MANYCHAT_SHARED_SECRET=manychat-secret:latest"

echo ""
echo "Done. URLs:"
gcloud functions describe send-sms --region="$REGION" --gen2 --format='value(serviceConfig.uri)'
gcloud functions describe sms-callback --region="$REGION" --gen2 --format='value(serviceConfig.uri)'
