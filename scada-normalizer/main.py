import json as json_lib
import base64
import logging
import os
import uuid
from datetime import datetime, timezone
from flask import Flask, request
from pydantic import BaseModel, validator
from google.cloud import pubsub_v1, bigquery

# Configure logging
logging.basicConfig(level=logging.INFO)

app = Flask(__name__)

class RawScadaEvent(BaseModel):
    device_id: str
    status: str
    timestamp: str

    @validator('status')
    def validate_status(cls, v):
        if v not in ("ON", "OFF"):
            raise ValueError('status must be "ON" or "OFF"')
        return v

@app.route("/_ah/warmup")
def warmup():
    return ("", 200)

@app.route("/", methods=["POST"])
def normalize():
    try:
        envelope = request.get_json()
        if not envelope or "message" not in envelope:
            logging.warning("Bad request: missing 'message'")
            return "Bad Request", 400

        pubsub_message = envelope["message"]
        if "data" not in pubsub_message:
            logging.warning("Bad request: missing 'data'")
            return "Bad Request", 400

        # Parse raw 
        raw_data = json_lib.loads(base64.b64decode(pubsub_message["data"]).decode("utf-8"))
        logging.info(f"📥 Received raw SCADA: {raw_data}")

        # Validate schema
        validated = RawScadaEvent(**raw_data)

        # 💡 FIX: Use proper BigQuery timestamp format
        current_time_str = datetime.now(timezone.utc).isoformat()
        event_timestamp = validated.timestamp.replace("Z", "+00:00") if validated.timestamp.endswith("Z") else validated.timestamp
        
        # === ENRICHMENT ===
        enriched = {
            "device_id": validated.device_id,
            "status": validated.status,
            "timestamp": event_timestamp,  # 💡 Proper BigQuery timestamp format
            "source_system": "SCADA",
            "event_id": str(uuid.uuid4()),
            "normalized_at": current_time_str,  # 💡 Proper BigQuery timestamp format
            "asset_type": "transformer",  # More specific than "unknown"
            "network_id": "default_feeder",
            "confidence_score": 1.0,  # 💡 Add missing required field
            "metadata": json_lib.dumps({})  # 💥 CRITICAL FIX: Convert dict to JSON string
        }

        PROJECT_ID = os.environ["PROJECT_ID"]

        # === PUBLISH TO PUB/SUB ===
        OUTPUT_TOPIC = f"projects/{PROJECT_ID}/topics/telemetry-normalized"
        publisher = pubsub_v1.PublisherClient()
        future = publisher.publish(OUTPUT_TOPIC, json_lib.dumps(enriched).encode("utf-8"))
        future.result(timeout=10)
        logging.info(f"✅ Published to Pub/Sub for {validated.device_id}")

        # === WRITE TO BIGQUERY - USE CONSISTENT TABLES ===
        try:
            client = bigquery.Client()
            
            # Write to CONSISTENT normalized table (same as other normalizers)
            norm_errors = client.insert_rows_json(
                "oms.normalized_telemetry",  # 💡 Use same table as AMI/Call Center
                [enriched]
            )
            if norm_errors:
                logging.warning(f"BigQuery normalized_telemetry errors: {norm_errors}")
            else:
                logging.info("✅ Successfully wrote normalized data to BigQuery")

            # Write to CONSISTENT raw table
            raw_record = {
                "ingest_timestamp": current_time_str,
                "pubsub_message_id": envelope.get("messageId", ""),
                "source_system": "SCADA",
                "raw_data": json_lib.dumps(raw_data)  # 💥 CRITICAL FIX: Convert dict to JSON string
            }
            raw_errors = client.insert_rows_json(
                "oms.raw_telemetry",  # 💡 Use same table as AMI/Call Center
                [raw_record]
            )
            if raw_errors:
                logging.warning(f"BigQuery raw_telemetry errors: {raw_errors}")
            else:
                logging.info("✅ Successfully wrote raw data to BigQuery")

        except Exception as bq_error:
            # 🚨 NEVER let BigQuery failures break the main pipeline
            logging.error(f"BigQuery write failed (but pipeline continues): {str(bq_error)}")

        return ("", 204)

    except Exception as e:
        logging.exception("🔥 Normalization failed")
        return ("Error", 500)