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

        # === ENRICHMENT ===
        # Keep ALL values as JSON-serializable types (strings, numbers, booleans)
        current_time_str = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        
        enriched = {
            "device_id": validated.device_id,
            "status": validated.status,
            "timestamp": validated.timestamp,  # Keep original string
            "source_system": "SCADA",
            "event_id": str(uuid.uuid4()),
            "normalized_at": current_time_str,  # ISO string, not datetime object
            "asset_type": "unknown",
            "network_id": "default_feeder"
        }

        PROJECT_ID = os.environ["PROJECT_ID"]

        # === PUBLISH TO PUB/SUB ===
        OUTPUT_TOPIC = f"projects/{PROJECT_ID}/topics/telemetry-normalized"
        publisher = pubsub_v1.PublisherClient()
        future = publisher.publish(OUTPUT_TOPIC, json_lib.dumps(enriched).encode("utf-8"))
        future.result(timeout=10)
        logging.info(f"✅ Published to Pub/Sub for {validated.device_id}")

        # === WRITE TO BIGQUERY ===
        client = bigquery.Client()
        
        # Write RAW data
        try:
            raw_record = {
                "ingest_timestamp": current_time_str,
                "pubsub_message_id": envelope.get("messageId", ""),
                "raw_data": json_lib.dumps(raw_data)
            }
            raw_errors = client.insert_rows_json(
                "oms.raw_scada_events",
                [raw_record]
            )
            if raw_errors:
                logging.error(f"BigQuery raw insert errors: {raw_errors}")
            else:
                logging.info("✅ Successfully wrote raw data to BigQuery")
        except Exception as raw_error:
            logging.error(f"BigQuery raw write failed: {str(raw_error)}")

        # Write NORMALIZED data
        try:
            norm_errors = client.insert_rows_json(
                "oms.normalized_scada_events",
                [enriched]
            )
            if norm_errors:
                logging.error(f"BigQuery normalized insert errors: {norm_errors}")
            else:
                logging.info("✅ Successfully wrote normalized data to BigQuery")
        except Exception as norm_error:
            logging.error(f"BigQuery normalized write failed: {str(norm_error)}")

        return ("", 204)

    except Exception as e:
        logging.exception("🔥 Normalization failed")
        return ("Error", 500)