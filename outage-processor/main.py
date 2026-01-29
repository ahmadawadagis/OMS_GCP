import json
import base64
import logging
import os
from datetime import datetime
from flask import Flask, request

logging.basicConfig(level=logging.INFO)
app = Flask(__name__)

@app.route("/_ah/warmup")
def warmup():
    return ("", 204)

@app.route("/", methods=["POST"])
def process_outage():
    # Always acknowledge first to prevent retries
    try:
        envelope = request.get_json()
        if not envelope or "message" not in envelope:
            logging.warning("Bad request: missing 'message'")
            return ("", 204)  # Still ack to avoid retries

        pubsub_message = envelope["message"]
        if "data" not in pubsub_message:
            logging.warning("Bad request: missing 'data'")
            return ("", 204)  # Ack bad messages to avoid retry loop

        # Parse message
        data = json.loads(base64.b64decode(pubsub_message["data"]).decode("utf-8"))
        logging.info(f"📥 Received normalized event: {data}")

        # Validate required fields
        required_fields = ["device_id", "status", "source_system", "timestamp"]
        if not all(field in data for field in required_fields):
            logging.warning(f"Missing required fields in event: {data}")
            return ("", 204)  # Ack invalid messages

        device_id = data["device_id"]
        status = data["status"]
        source_system = data["source_system"]
        event_time = data["timestamp"]

        # Process only after acknowledgment
        _process_event(device_id, status, source_system, event_time, data)

        return ("", 204)

    except Exception as e:
        logging.error(f"🔥 Processing error (but acknowledged): {str(e)}")
        # STILL RETURN 204 TO PREVENT RETRIES
        return ("", 204)

def _process_event(device_id, status, source_system, event_time, data):
    """Actual processing logic - isolated from Pub/Sub acknowledgment"""
    from google.cloud import pubsub_v1, firestore
    
    PROJECT_ID = os.environ["PROJECT_ID"]
    db = firestore.Client()
    publisher = pubsub_v1.PublisherClient()
    OUTAGE_TOPIC = f"projects/{PROJECT_ID}/topics/outages"

    doc_ref = db.collection("device_status").document(device_id)
    doc = doc_ref.get()
    current_state = doc.to_dict() if doc.exists else None
    logging.info(f"🔍 Device {device_id} state: {current_state}")

    should_create_outage = False
    priority = "NORMAL"

    if source_system == "CALL_CENTER" and status == "OUTAGE_REPORTED":
        if current_state and current_state.get("status") == "OFF":
            should_create_outage = True
            priority = "CONFIRMED"
        else:
            logging.info(f"📞 Call center report for {device_id} – awaiting SCADA/AMI confirmation")
            return

    elif source_system in ["SCADA", "AMI"] and status == "OFF":
        if not current_state or current_state.get("status") != "OFF":
            should_create_outage = True
            if source_system == "AMI":
                priority = "METER_BASED"

    if should_create_outage:
        import uuid
        outage_id = str(uuid.uuid4())
        outage_event = {
            "outage_id": outage_id,
            "device_id": device_id,
            "start_time": event_time,
            "source_system": source_system,
            "priority": priority,
            "status": "ACTIVE"
        }

        future = publisher.publish(OUTAGE_TOPIC, json.dumps(outage_event).encode("utf-8"))
        future.result(timeout=10)
        logging.info(f"✅ Created outage: {outage_id} (priority: {priority})")

        doc_ref.set({
            "status": "OFF",
            "outage_id": outage_id,
            "last_update": firestore.SERVER_TIMESTAMP,
            "confirmed_by": source_system
        })

    elif status == "ON" and current_state and current_state.get("status") == "OFF":
        doc_ref.set({
            "status": "ON",
            "last_update": firestore.SERVER_TIMESTAMP
        })
        logging.info(f"🔌 Device {device_id} restored")