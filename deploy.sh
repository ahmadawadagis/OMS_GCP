#!/bin/bash
set -e

PROJECT_ID="omsgis"
REGION="us-central1"

echo "🚀 Deploying OMS Pipeline to project: $PROJECT_ID"

# --- Check if Firestore is initialized ---
echo "🔍 Checking Firestore status..."
if ! gcloud firestore indexes composite list --project=$PROJECT_ID >/dev/null 2>&1; then
  echo ""
  echo "⚠️  Firestore is not initialized in project '$PROJECT_ID'."
  echo "👉 Please initialize Firestore in NATIVE MODE before proceeding:"
  echo "   1. Go to https://console.cloud.google.com/firestore"
  echo "   2. Click 'Create Database'"
  echo "   3. Select 'Native Mode'"
  echo "   4. Choose location: us-central1"
  echo "   5. Click 'Create'"
  echo ""
  echo "After creating Firestore, re-run this script."
  exit 1
fi
echo "✅ Firestore is ready."

# Enable required APIs
gcloud services enable \
  pubsub.googleapis.com \
  firestore.googleapis.com \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  --project=$PROJECT_ID

# Set project context
gcloud config set project $PROJECT_ID

# Create Pub/Sub topics (ignore if already exist)
gcloud pubsub topics create scada-raw --quiet 2>/dev/null || true
gcloud pubsub topics create scada-normalized --quiet 2>/dev/null || true
gcloud pubsub topics create outages --quiet 2>/dev/null || true

# === IAM Setup ===
echo "🔑 Configuring IAM permissions..."

PROJECT_NUMBER=$(gcloud projects describe $PROJECT_ID --format="value(projectNumber)")
SERVICE_ACCOUNT="$PROJECT_NUMBER-compute@developer.gserviceaccount.com"

# Required for Cloud Run source deployments (GCS access)
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$SERVICE_ACCOUNT" \
  --role="roles/storage.objectViewer" \
  --quiet

# Required for Firestore access
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$SERVICE_ACCOUNT" \
  --role="roles/datastore.user" \
  --quiet

# Optional but helpful for dev: broader access
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$SERVICE_ACCOUNT" \
  --role="roles/editor" \
  --quiet

echo "✅ IAM configured."

# === Deploy Services ===
echo "📦 Deploying scada-normalizer..."
cd scada-normalizer
gcloud run deploy scada-normalizer \
  --source . \
  --platform managed \
  --region $REGION \
  --allow-unauthenticated \
  --set-env-vars PROJECT_ID=$PROJECT_ID,GUNICORN_CMD_ARGS="--timeout 90" \
  --project=$PROJECT_ID

echo "📦 Deploying outage-processor..."
cd ../outage-processor
gcloud run deploy outage-processor \
  --source . \
  --platform managed \
  --region $REGION \
  --allow-unauthenticated \
  --set-env-vars PROJECT_ID=$PROJECT_ID,GUNICORN_CMD_ARGS="--timeout 90" \
  --project=$PROJECT_ID

# === Get Public URLs ===
NORMALIZER_URL=$(gcloud run services describe scada-normalizer --region $REGION --format='value(status.url)' --project=$PROJECT_ID)
OUTAGE_URL=$(gcloud run services describe outage-processor --region $REGION --format='value(status.url)' --project=$PROJECT_ID)

# === Clean & Recreate Subscriptions ===
echo "🔁 Setting up Pub/Sub subscriptions..."
gcloud pubsub subscriptions delete scada-normalizer-sub --quiet --project=$PROJECT_ID 2>/dev/null || true
gcloud pubsub subscriptions delete outage-processor-sub --quiet --project=$PROJECT_ID 2>/dev/null || true
gcloud pubsub subscriptions delete test-outages --quiet --project=$PROJECT_ID 2>/dev/null || true

gcloud pubsub subscriptions create scada-normalizer-sub \
  --topic scada-raw \
  --push-endpoint=$NORMALIZER_URL \
  --project=$PROJECT_ID

gcloud pubsub subscriptions create outage-processor-sub \
  --topic scada-normalized \
  --push-endpoint=$OUTAGE_URL \
  --project=$PROJECT_ID

gcloud pubsub subscriptions create test-outages --topic outages --quiet --project=$PROJECT_ID

echo ""
echo "✅ Deployment completed successfully!"
echo "🧪 Test with:"
echo "  gcloud pubsub topics publish scada-raw --message='{\"device_id\":\"D-$(date +%s)\",\"status\":\"OFF\",\"timestamp\":\"2026-01-26T17:00:00Z\"}'"
echo "  sleep 45"
echo "  gcloud pubsub subscriptions pull test-outages --auto-ack"