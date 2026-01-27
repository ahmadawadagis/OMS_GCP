import json
import base64
import logging
import os
import uuid
from flask import Flask, request

# Configure logging
logging.basicConfig(level=logging.INFO)

app = Flask(__name__)

@app.route("/_ah/warmup")
def warmup():
    """Handle Cloud Run warmup requests."""
    return ("", 200)

@app.route("/", methods=["POST"])
def process_outage():
    try:
        # Lazy imports — critical for cold start performance
        from google.cloud import pubsub_v1, firestore

        PROJECT_ID = os.environ["PROJECT_ID"]
        OUTAGE_TOPIC = f"projects/{PROJECT_ID}/topics/outages"
        publisher = pubsub_v1.PublisherClient()
        db = firestore.Client()

        envelope = request.get_json()
        if not envelope or "message" not in envelope:
            logging.warning("Bad request: missing 'message' field")
            return "Bad Request", 400

        pubsub_message = envelope["message"]
        if "data" not in pubsub_message:
            logging.warning("Bad request: missing 'data' in message")
            return "Bad Request", 400

        data = json.loads(base64.b64decode(pubsub_message["data"]).decode("utf-8"))
        logging.info(f"📥 Received SCADA event: {data}")

        device_id = data["device_id"]
        new_status = data["status"]
        event_time = data["timestamp"]

        doc_ref = db.collection("device_status").document(device_id)
        doc = doc_ref.get()
        current_state = doc.to_dict() if doc.exists else None
        logging.info(f"🔍 Device {device_id} state: {current_state}")

        if new_status == "OFF":
            if not current_state or current_state.get("status") != "OFF":
                outage_id = str(uuid.uuid4())
                outage_event = {
                    "outage_id": outage_id,
                    "device_id": device_id,
                    "start_time": event_time,
                    "status": "ACTIVE"
                }

                future = publisher.publish(OUTAGE_TOPIC, json.dumps(outage_event).encode("utf-8"))
                future.result(timeout=10)  # Wait for publish
                logging.info(f"✅ Published outage: {outage_id}")

                doc_ref.set({
                    "status": "OFF",
                    "outage_id": outage_id,
                    "last_update": firestore.SERVER_TIMESTAMP
                })
                logging.info(f"💾 Saved OFF state for {device_id}")
            else:
                logging.info(f"⏭️ Duplicate OFF event for {device_id} — skipped")

        elif new_status == "ON":
            if current_state and current_state.get("status") == "OFF":
                doc_ref.set({
                    "status": "ON",
                    "last_update": firestore.SERVER_TIMESTAMP
                })
                logging.info(f"🔌 Device {device_id} restored to ON")

        return ("", 204)

    except Exception as e:
        # 🔥 ADD THIS LINE TO SEE THE ACTUAL ERROR MESSAGE
        logging.error(f"🔥 FATAL ERROR: {str(e)}")
        logging.exception("Full traceback:")
        return ("Error", 500)