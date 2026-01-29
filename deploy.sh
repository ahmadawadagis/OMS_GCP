#!/bin/bash
set -e

# Always run from script directory
cd "$(dirname "$0")"

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
TOPICS=(
  "scada-raw"
  "scada-normalized"
  "outages"
  "ami-raw"
  "callcenter-raw"
  "telemetry-normalized"
)

for TOPIC in "${TOPICS[@]}"; do
  gcloud pubsub topics create "$TOPIC" --quiet 2>/dev/null || true
done

# === IAM Setup ===
echo "🔑 Configuring IAM permissions..."

PROJECT_NUMBER=$(gcloud projects describe $PROJECT_ID --format="value(projectNumber)")
SERVICE_ACCOUNT="$PROJECT_NUMBER-compute@developer.gserviceaccount.com"

# Required permissions
PERMISSIONS=(
  "roles/storage.objectViewer"
  "roles/datastore.user"
  "roles/bigquery.dataEditor"
  "roles/editor"
)

for ROLE in "${PERMISSIONS[@]}"; do
  gcloud projects add-iam-policy-binding $PROJECT_ID \
    --member="serviceAccount:$SERVICE_ACCOUNT" \
    --role="$ROLE" \
    --quiet
done

echo "✅ IAM configured."

# === Deploy Services ===
SERVICES=(
  "scada-normalizer"
  "ami-normalizer"
  "callcenter-normalizer"
  "outage-processor"
)

for SERVICE in "${SERVICES[@]}"; do
  echo "📦 Deploying $SERVICE..."
  cd "$SERVICE"
  gcloud run deploy "$SERVICE" \
    --source . \
    --platform managed \
    --region $REGION \
    --allow-unauthenticated \
    --set-env-vars PROJECT_ID=$PROJECT_ID,GUNICORN_CMD_ARGS="--timeout 90" \
    --project=$PROJECT_ID
  cd ..
done

# === Get Public URLs ===
NORMALIZER_URL=$(gcloud run services describe scada-normalizer --region $REGION --format='value(status.url)' --project=$PROJECT_ID)
AMI_URL=$(gcloud run services describe ami-normalizer --region $REGION --format='value(status.url)' --project=$PROJECT_ID)
CALLCENTER_URL=$(gcloud run services describe callcenter-normalizer --region $REGION --format='value(status.url)' --project=$PROJECT_ID)
OUTAGE_URL=$(gcloud run services describe outage-processor --region $REGION --format='value(status.url)' --project=$PROJECT_ID)

# === Clean & Recreate Subscriptions ===
echo "🔁 Setting up Pub/Sub subscriptions..."

# Delete existing subscriptions
SUBS_TO_DELETE=(
  "scada-normalizer-sub"
  "ami-normalizer-sub"
  "callcenter-normalizer-sub"
  "outage-processor-sub"
  "test-outages"
)

for SUB in "${SUBS_TO_DELETE[@]}"; do
  gcloud pubsub subscriptions delete "$SUB" --quiet --project=$PROJECT_ID 2>/dev/null || true
done

# Create new subscriptions
gcloud pubsub subscriptions create scada-normalizer-sub \
  --topic scada-raw \
  --push-endpoint=$NORMALIZER_URL \
  --project=$PROJECT_ID

gcloud pubsub subscriptions create ami-normalizer-sub \
  --topic ami-raw \
  --push-endpoint=$AMI_URL \
  --project=$PROJECT_ID

gcloud pubsub subscriptions create callcenter-normalizer-sub \
  --topic callcenter-raw \
  --push-endpoint=$CALLCENTER_URL \
  --project=$PROJECT_ID

gcloud pubsub subscriptions create outage-processor-sub \
  --topic telemetry-normalized \
  --push-endpoint=$OUTAGE_URL \
  --project=$PROJECT_ID

gcloud pubsub subscriptions create test-outages \
  --topic outages \
  --quiet \
  --project=$PROJECT_ID

echo ""
echo "✅ Deployment completed successfully!"
echo "🧪 Test commands:"
echo "  # SCADA event"
echo "  gcloud pubsub topics publish scada-raw --message='{\"device_id\":\"D-SCADA-\$(date +\%s)\",\"status\":\"OFF\",\"timestamp\":\"2026-01-28T10:00:00Z\"}'"
echo ""
echo "  # AMI event"
echo "  gcloud pubsub topics publish ami-raw --message='{\"meter_id\":\"M-AMI-\$(date +\%s)\",\"voltage\":85,\"reading_time\":\"2026-01-28T10:00:00Z\",\"feeder_id\":\"FEEDER-A\"}'"
echo ""
echo "  # Call Center event"
echo "  gcloud pubsub topics publish callcenter-raw --message='{\"customer_account_id\":\"CUST-\$(date +\%s)\",\"call_timestamp\":\"2026-01-28T10:00:00Z\",\"issue_description\":\"No power\"}'"
echo ""
echo "  # Check results after 45 seconds"
echo "  gcloud pubsub subscriptions pull test-outages --auto-ack"