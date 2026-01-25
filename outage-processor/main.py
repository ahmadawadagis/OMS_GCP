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
    envelope = request.get_json(silent=True)
    if not envelope or "message" not in envelope:
        print("Bad request: missing 'message' field")
        return ("Bad Request", 400)

    msg = envelope["message"]
    data = msg.get("data")
    if not data:
        print("No data in message")
        return ("No data", 400)

    # Decode Pub/Sub message
    try:
        payload = json.loads(base64.b64decode(data).decode("utf-8"))
    except Exception as e:
        print(f"Failed to decode message: {e}")
        return ("Bad Request", 400)

    # SCADA messages may contain a single device or a list of devices
    devices = payload if isinstance(payload, list) else [payload]

    outages = []  # Collect all outages for batch publishing

    for event in devices:
        measurements = event.get("measurements", {})
        voltage = measurements.get("voltage_kv")  # None if missing
        current = measurements.get("current_a")
        state = event.get("state", "UNKNOWN")
        asset = event.get("asset")  # Could be None
        event_id = event.get("event_id") or str(uuid.uuid4())
        timestamp = event.get("timestamp") or None

        # Determine if this is an outage
        is_outage = (voltage is not None and voltage < 10) or (state.upper() == "DOWN")

        if is_outage:
            if not asset or not timestamp:
                print(f"Skipping outage: missing asset or timestamp: {event}")
                continue

            outage_event = {
                "incident_type": "OUTAGE_DETECTED",
                "event_id": event_id,
                "asset": asset,
                "detected_by": "outage-processor",
                "reason": "voltage<10kV or state=DOWN",
                "voltage_kv": voltage,
                "current_a": current,
                "state": state,
                "timestamp": timestamp,
            }

            outages.append(outage_event)
        else:
            print(f"Ignored normal message: {event}")

    # Batch publish if we have any outages
    if outages:
        try:
            publisher.publish(
                out_topic_path,
                json.dumps(outages).encode("utf-8"),
            )
            print(f"Published batch of {len(outages)} outages")
        except Exception as e:
            print(f"Failed to publish batch: {e}")

    return ("", 204)


@app.route("/health", methods=["GET"])
def health():
    return "OK", 200
