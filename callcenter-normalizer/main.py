import json as json_lib
import base64
import logging
import os
import uuid
from datetime import datetime, timezone
from flask import Flask, request
from google.cloud import pubsub_v1, bigquery

logging.basicConfig(level=logging.INFO)
app = Flask(__name__)

@app.route("/_ah/warmup")
def warmup():
    return ("", 204)

@app.route("/", methods=["POST"])
def normalize():
    try:
        envelope = request.get_json()
        if not envelope or "message" not in envelope:
            return "Bad Request", 400

        pubsub_message = envelope["message"]
        if "data" not in pubsub_message:
            return "Bad Request", 400

        raw_data = json_lib.loads(base64.b64decode(pubsub_message["data"]).decode("utf-8"))
        logging.info(f"📞 Received Call Center: {raw_data}")

        # 💡 FIX: Use proper BigQuery timestamp format
        normalized_timestamp = datetime.now(timezone.utc).isoformat()
        event_timestamp = raw_data["call_timestamp"].replace("Z", "+00:00") if raw_data["call_timestamp"].endswith("Z") else raw_data["call_timestamp"]

        enriched = {
            "event_id": str(uuid.uuid4()),
            "source_system": "CALL_CENTER",
            "device_id": raw_data["customer_account_id"],
            "status": "OUTAGE_REPORTED",
            "timestamp": event_timestamp,  # 💡 Proper BigQuery timestamp format
            "normalized_at": normalized_timestamp,  # 💡 Proper BigQuery timestamp format
            "asset_type": "customer",
            "network_id": raw_data.get("service_address_feeder", "unknown"),
            "confidence_score": 0.7,
            "metadata": json_lib.dumps({  # 💥 CRITICAL FIX: Convert dict to JSON string
                "caller_name": raw_data.get("caller_name"),
                "issue_description": raw_data.get("issue_description"),
                "call_duration_sec": raw_data.get("call_duration_sec")
            })
        }

        PROJECT_ID = os.environ["PROJECT_ID"]
        OUTPUT_TOPIC = f"projects/{PROJECT_ID}/topics/telemetry-normalized"
        
        publisher = pubsub_v1.PublisherClient()
        future = publisher.publish(OUTPUT_TOPIC, json_lib.dumps(enriched).encode("utf-8"))
        future.result(timeout=10)

        # 💡 CRITICAL: Handle BigQuery writes separately with error tolerance
        try:
            client = bigquery.Client()
            # Write normalized data
            errors1 = client.insert_rows_json("oms.normalized_telemetry", [enriched])
            if errors1:
                logging.warning(f"BigQuery normalized_telemetry errors: {errors1}")
            
            # Write raw data  
            raw_record = {
                "ingest_timestamp": normalized_timestamp,  # 💡 Match timestamp format
                "pubsub_message_id": envelope.get("messageId", ""),
                "source_system": "CALL_CENTER",
                "raw_data": json_lib.dumps(raw_data)  # ✅ Already correct in your code
            }
            errors2 = client.insert_rows_json("oms.raw_telemetry", [raw_record])
            if errors2:
                logging.warning(f"BigQuery raw_telemetry errors: {errors2}")
                
        except Exception as bq_error:
            # 🚨 NEVER let BigQuery failures break the main pipeline
            logging.error(f"BigQuery write failed (but pipeline continues): {str(bq_error)}")

        return ("", 204)

    except Exception as e:
        logging.exception("🔥 Call Center normalization failed")
        return ("Error", 500)