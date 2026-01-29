#!/bin/bash
set -e

echo "🚀 Clean OMS Test (no variables in messages)"
echo "==========================================="

# Use static but unique IDs (no shell variables in JSON)
SCADA_ID="D-SCADA-CLEAN-$(date +%s)"
AMI_ID="M-AMI-CLEAN-$(date +%s)"
CALL_ID="C-CALL-CLEAN-$(date +%s)"
CORR_ID="CORR-CLEAN-$(date +%s)"

echo "Publishing SCADA: $SCADA_ID"
gcloud pubsub topics publish scada-raw --message="{\"device_id\":\"$SCADA_ID\",\"status\":\"OFF\",\"timestamp\":\"2026-01-28T23:00:00Z\"}"

echo "Publishing AMI: $AMI_ID"
gcloud pubsub topics publish ami-raw --message="{\"meter_id\":\"$AMI_ID\",\"voltage\":80,\"reading_time\":\"2026-01-28T23:00:00Z\"}"

echo "Publishing Call Center: $CALL_ID"
gcloud pubsub topics publish callcenter-raw --message="{\"customer_account_id\":\"$CALL_ID\",\"call_timestamp\":\"2026-01-28T23:00:00Z\",\"issue_description\":\"Test\"}"

echo "Publishing Correlated: $CORR_ID"
gcloud pubsub topics publish callcenter-raw --message="{\"customer_account_id\":\"$CORR_ID\",\"call_timestamp\":\"2026-01-28T23:00:00Z\",\"issue_description\":\"Confirm\"}"
sleep 3
gcloud pubsub topics publish scada-raw --message="{\"device_id\":\"$CORR_ID\",\"status\":\"OFF\",\"timestamp\":\"2026-01-28T23:00:05Z\"}"

echo ""
echo "✅ All messages sent. Check Firestore for:"
echo "• $SCADA_ID"
echo "• $AMI_ID"
echo "• $CORR_ID"
echo "(Call Center $CALL_ID should NOT appear)"