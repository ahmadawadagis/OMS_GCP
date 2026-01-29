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
    return ("", 200)

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
        logging.info(f"📥 Received AMI: {raw_data}")

        # 💡 FIX: Use proper BigQuery timestamp format
        normalized_timestamp = datetime.now(timezone.utc).isoformat()
        event_timestamp = raw_data["reading_time"].replace("Z", "+00:00") if raw_data["reading_time"].endswith("Z") else raw_data["reading_time"]

        # Map AMI → common schema
        enriched = {
            "event_id": str(uuid.uuid4()),
            "source_system": "AMI",
            "device_id": raw_data["meter_id"],
            "status": "OFF" if float(raw_data.get("voltage", 120)) < 90 else "ON",
            "timestamp": event_timestamp,  # 💡 Proper BigQuery timestamp format
            "normalized_at": normalized_timestamp,  # 💡 Proper BigQuery timestamp format
            "asset_type": "meter",
            "network_id": raw_data.get("feeder_id", "unknown"),
            "confidence_score": 1.0,  # 💡 Add missing field for schema consistency
            "metadata": json_lib.dumps({  # 💥 CRITICAL FIX: Convert dict to JSON string
                "voltage": raw_data.get("voltage"),
                "amr_status": raw_data.get("amr_status")
            })
        }

        PROJECT_ID = os.environ["PROJECT_ID"]
        OUTPUT_TOPIC = f"projects/{PROJECT_ID}/topics/telemetry-normalized"
        
        publisher = pubsub_v1.PublisherClient()
        future = publisher.publish(OUTPUT_TOPIC, json_lib.dumps(enriched).encode("utf-8"))
        future.result(timeout=10)

        # 💡 CRITICAL: Handle BigQuery writes with error tolerance
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
                "source_system": "AMI",
                "raw_data": json_lib.dumps(raw_data)  # 💥 CRITICAL FIX: Convert dict to JSON string
            }
            errors2 = client.insert_rows_json("oms.raw_telemetry", [raw_record])
            if errors2:
                logging.warning(f"BigQuery raw_telemetry errors: {errors2}")
                
        except Exception as bq_error:
            # 🚨 NEVER let BigQuery failures break the main pipeline
            logging.error(f"BigQuery write failed (but pipeline continues): {str(bq_error)}")

        return ("", 204)

    except Exception as e:
        logging.exception("🔥 AMI normalization failed")
        return ("Error", 500)