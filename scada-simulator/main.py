import os
import json
from datetime import datetime, timezone
from flask import Flask
from google.cloud import pubsub_v1
import random

PROJECT_ID = os.environ["PROJECT_ID"]
TOPIC_ID = os.environ["TOPIC_ID"]

publisher = pubsub_v1.PublisherClient()
topic_path = publisher.topic_path(PROJECT_ID, TOPIC_ID)

app = Flask(__name__)

TRANSFORMERS = ["TX-001", "TX-002", "TX-003"]

@app.route("/simulate", methods=["POST", "GET"])
def simulate():
    tx = random.choice(TRANSFORMERS)
    is_outage = random.random() < 0.1  # 10% chance

    payload = {
        "device_id": tx,
        "device_type": "transformer",
        "feeder_id": "FD-12",
        "substation": "SUB-3",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "voltage_kv": 0.0 if is_outage else 11.0,
        "current_a": 0 if is_outage else random.uniform(50, 120),
        "status": "DOWN" if is_outage else "UP",
        "alarm_code": "TRF_OUT" if is_outage else None,
    }

    data = json.dumps(payload).encode("utf-8")
    future = publisher.publish(topic_path, data)
    future.result()

    return {
    "published": True,
    "outage": is_outage,
    "device": tx,
    "payload": payload,  # include full message
}, 200

@app.route("/")
def index():
    return "SCADA simulator running", 200