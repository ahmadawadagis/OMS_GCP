import os
import json
import base64
import uuid
from flask import Flask, request
from google.cloud import pubsub_v1

PROJECT_ID = os.environ["PROJECT_ID"]
OUT_TOPIC_ID = os.environ["OUT_TOPIC_ID"]

publisher = pubsub_v1.PublisherClient()
out_topic_path = publisher.topic_path(PROJECT_ID, OUT_TOPIC_ID)

app = Flask(__name__)

@app.route("/", methods=["POST"])
def handle_message():
    envelope = request.get_json()
    if not envelope or "message" not in envelope:
        return ("Bad Request", 400)

    msg = envelope["message"]
    data = msg.get("data")
    if not data:
        return ("No data", 400)

    raw = json.loads(base64.b64decode(data).decode("utf-8"))

    # --- Normalization ---
    normalized_event = {
        "event_id": str(uuid.uuid4()),
        "event_type": "ASSET_TELEMETRY",
        "domain": "ELECTRIC",
        "source": "SCADA",
        "asset": {
            "asset_id": raw.get("device_id"),
            "asset_type": raw.get("device_type", "UNKNOWN"),
            "feeder_id": raw.get("feeder_id"),
            "substation": raw.get("substation"),
        },
        "measurements": {
            "voltage_kv": raw.get("voltage_kv"),
            "current_a": raw.get("current_a"),
        },
        "state": raw.get("status"),
        "alarm_code": raw.get("alarm_code"),
        "timestamp": raw.get("timestamp"),
    }

    publisher.publish(
        out_topic_path,
        json.dumps(normalized_event).encode("utf-8"),
    )

    return ("", 204)

@app.route("/health", methods=["GET"])
def health():
    return "OK", 200
