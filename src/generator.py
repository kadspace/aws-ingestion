import base64
import json
import os
import random
import uuid
from datetime import datetime, timezone

import boto3

sqs = boto3.client("sqs")
QUEUE_URL = os.environ["QUEUE_URL"]

MACHINES = ["machine-001", "machine-002", "machine-003"]

MAX_READINGS_PER_REQUEST = 25
NUMERIC_FIELDS = ("temperature_f", "vibration_mm_s", "pressure_psi", "rpm")


def derive_severity(temperature: float, vibration: float) -> str:
    if temperature >= 95 or vibration >= 0.25:
        return "high"
    if temperature >= 88 or vibration >= 0.18:
        return "medium"
    return "low"


def make_reading(machine_id: str) -> dict:
    temperature = round(random.normalvariate(82, 7), 2)
    vibration = round(max(0.01, random.normalvariate(0.12, 0.05)), 4)
    pressure = round(random.normalvariate(55, 6), 2)
    rpm = int(random.normalvariate(1750, 120))

    return {
        "reading_id": str(uuid.uuid4()),
        "machine_id": machine_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "temperature_f": temperature,
        "vibration_mm_s": vibration,
        "pressure_psi": pressure,
        "rpm": rpm,
        "severity": derive_severity(temperature, vibration),
    }


def parse_submitted_reading(payload) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("each reading must be a JSON object")

    machine_id = payload.get("machine_id")
    if not isinstance(machine_id, str) or not machine_id.strip():
        raise ValueError("machine_id must be a non-empty string")

    for field in NUMERIC_FIELDS:
        value = payload.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{field} must be a number")

    timestamp = payload.get("timestamp", datetime.now(timezone.utc).isoformat())
    if not isinstance(timestamp, str) or not timestamp.strip():
        raise ValueError("timestamp must be a string")

    return {
        "reading_id": str(uuid.uuid4()),
        "machine_id": machine_id.strip(),
        "timestamp": timestamp,
        "temperature_f": payload["temperature_f"],
        "vibration_mm_s": payload["vibration_mm_s"],
        "pressure_psi": payload["pressure_psi"],
        "rpm": payload["rpm"],
        "severity": derive_severity(payload["temperature_f"], payload["vibration_mm_s"]),
    }


def send_readings(readings: list) -> None:
    for reading in readings:
        sqs.send_message(
            QueueUrl=QUEUE_URL,
            MessageBody=json.dumps(reading),
        )


def http_response(status_code: int, body: dict) -> dict:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def handle_http_request(event) -> dict:
    body = event.get("body") or ""

    if event.get("isBase64Encoded"):
        try:
            body = base64.b64decode(body).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return http_response(400, {"error": "request body must be valid JSON"})

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return http_response(400, {"error": "request body must be valid JSON"})

    submitted = payload if isinstance(payload, list) else [payload]

    if not submitted:
        return http_response(400, {"error": "request body must contain at least one reading"})

    if len(submitted) > MAX_READINGS_PER_REQUEST:
        return http_response(
            400,
            {"error": f"at most {MAX_READINGS_PER_REQUEST} readings per request"},
        )

    try:
        readings = [parse_submitted_reading(item) for item in submitted]
    except ValueError as e:
        return http_response(400, {"error": str(e)})

    send_readings(readings)

    return http_response(200, {"messages_sent": len(readings), "readings": readings})


def lambda_handler(event, context):
    if isinstance(event, dict) and event.get("requestContext", {}).get("http"):
        return handle_http_request(event)

    readings = [make_reading(machine_id) for machine_id in MACHINES]
    send_readings(readings)

    return {
        "messages_sent": len(readings),
        "readings": readings,
    }
