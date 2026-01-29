#!/bin/bash
set -e

# Use SAME device ID for both Call Center and SCADA
CORR_DEVICE="CORR-TEST-$(date +%s)"

echo "🔗 Testing correlation with device: $CORR_DEVICE"
echo "=========================================="

# 1. Publish Call Center event (should wait for confirmation)
echo "📞 Publishing Call Center event..."
gcloud pubsub topics publish callcenter-raw --message="{\"customer_account_id\":\"$CORR_DEVICE\",\"call_timestamp\":\"2026-01-29T10:00:00Z\",\"issue_description\":\"Customer reported outage\"}"

# 2. Publish SCADA event for SAME device (should trigger CONFIRMED outage)
echo "📡 Publishing SCADA event..."
gcloud pubsub topics publish scada-raw --message="{\"device_id\":\"$CORR_DEVICE\",\"status\":\"OFF\",\"timestamp\":\"2026-01-29T10:00:05Z\"}"

echo ""
echo "✅ Expected result:"
echo "• Firestore document: $CORR_DEVICE with priority: CONFIRMED"
echo "• One outage event in test-outages with priority: CONFIRMED"
echo ""
echo "⏳ Waiting 60 seconds for processing..."
sleep 60

# Check results
echo "📋 Outage events created:"
gcloud pubsub subscriptions pull test-outages --auto-ack --limit=5