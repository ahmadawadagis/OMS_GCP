# ami-normalizer/main.py
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

        # Map AMI → common schema
        enriched = {
            "event_id": str(uuid.uuid4()),
            "source_system": "AMI",
            "device_id": raw_data["meter_id"],
            "status": "OFF" if float(raw_data.get("voltage", 120)) < 90 else "ON",
            "timestamp": raw_data["reading_time"],
            "normalized_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "asset_type": "meter",
            "network_id": raw_data.get("feeder_id", "unknown"),
            "metadata": {
                "voltage": raw_data.get("voltage"),
                "amr_status": raw_data.get("amr_status")
            }
        }

        PROJECT_ID = os.environ["PROJECT_ID"]
        OUTPUT_TOPIC = f"projects/{PROJECT_ID}/topics/telemetry-normalized"
        
        publisher = pubsub_v1.PublisherClient()
        future = publisher.publish(OUTPUT_TOPIC, json_lib.dumps(enriched).encode("utf-8"))
        future.result(timeout=10)

        # Write to BigQuery
        client = bigquery.Client()
        client.insert_rows_json("oms.normalized_telemetry", [enriched])
        client.insert_rows_json("oms.raw_telemetry", [{
            "ingest_timestamp": enriched["normalized_at"],
            "pubsub_message_id": envelope.get("messageId", ""),
            "source_system": "AMI",
            "raw_data": json_lib.dumps(raw_data)
        }])

        return ("", 204)

    except Exception as e:
        logging.exception("🔥 AMI normalization failed")
        return ("Error", 500)