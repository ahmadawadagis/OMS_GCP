# 1. Delete ALL subscriptions
gcloud pubsub subscriptions delete scada-normalizer-sub ami-normalizer-sub callcenter-normalizer-sub outage-processor-sub test-outages --quiet

# 2. Delete ALL topics
gcloud pubsub topics delete scada-raw ami-raw callcenter-raw telemetry-normalized outages --quiet

# 3. Wait 2 minutes for full cleanup
echo "⏳ Waiting 2 minutes for Google to fully purge..."
sleep 120

# 4. Recreate topics
gcloud pubsub topics create scada-raw ami-raw callcenter-raw telemetry-normalized outages

# 5. Get service URLs
NORMALIZER_URL=$(gcloud run services describe scada-normalizer --region us-central1 --format='value(status.url)')
AMI_URL=$(gcloud run services describe ami-normalizer --region us-central1 --format='value(status.url)')
CALL_URL=$(gcloud run services describe callcenter-normalizer --region us-central1 --format='value(status.url)')
OUTAGE_URL=$(gcloud run services describe outage-processor --region us-central1 --format='value(status.url)')

# 6. Create fresh subscriptions
gcloud pubsub subscriptions create scada-normalizer-sub --topic scada-raw --push-endpoint=$NORMALIZER_URL
gcloud pubsub subscriptions create ami-normalizer-sub --topic ami-raw --push-endpoint=$AMI_URL
gcloud pubsub subscriptions create callcenter-normalizer-sub --topic callcenter-raw --push-endpoint=$CALL_URL
gcloud pubsub subscriptions create outage-processor-sub --topic telemetry-normalized --push-endpoint=$OUTAGE_URL
gcloud pubsub subscriptions create test-outages --topic outages --quiet

echo "✅ Pub/Sub fully reset!"