import json
import os
import random
import uuid
from datetime import datetime, timezone

import boto3

sqs = boto3.client("sqs")
QUEUE_URL = os.environ["QUEUE_URL"]

MACHINES = ["machine-001", "machine-002", "machine-003"]


def make_reading(machine_id: str) -> dict:
    temperature = round(random.normalvariate(82, 7), 2)
    vibration = round(max(0.01, random.normalvariate(0.12, 0.05)), 4)
    pressure = round(random.normalvariate(55, 6), 2)
    rpm = int(random.normalvariate(1750, 120))

    if temperature >= 95 or vibration >= 0.25:
        severity = "high"
    elif temperature >= 88 or vibration >= 0.18:
        severity = "medium"
    else:
        severity = "low"

    return {
        "reading_id": str(uuid.uuid4()),
        "machine_id": machine_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "temperature_f": temperature,
        "vibration_mm_s": vibration,
        "pressure_psi": pressure,
        "rpm": rpm,
        "severity": severity,
    }


def lambda_handler(event, context):
    readings = [make_reading(machine_id) for machine_id in MACHINES]

    for reading in readings:
        sqs.send_message(
            QueueUrl=QUEUE_URL,
            MessageBody=json.dumps(reading),
        )

    return {
        "messages_sent": len(readings),
        "readings": readings,
    }
