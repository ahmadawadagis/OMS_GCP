import os
import json
import base64
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

    payload = json.loads(base64.b64decode(data).decode("utf-8"))

    # Simple outage logic: voltage < 10 kV or status DOWN
    voltage = payload.get("voltage_kv", 0)
    status = payload.get("status", "UNKNOWN")

    is_outage = (voltage < 10) or (status == "DOWN")
    if is_outage:
        out_payload = {
            **payload,
            "detected_by": "outage-processor",
            "reason": f"voltage<{10} or status=DOWN",
        }
        future = publisher.publish(
            out_topic_path,
            json.dumps(out_payload).encode("utf-8"),
        )
        future.result()

    return ("", 204)

@app.route("/health", methods=["GET"])
def health():
    return "OK", 200