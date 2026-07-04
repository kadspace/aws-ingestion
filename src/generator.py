import json
import random
import uuid
from datetime import datetime, timezone


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

    return {
        "statusCode": 200,
        "body": json.dumps({"readings": readings}),
    }


if __name__ == "__main__":
    result = lambda_handler({}, None)
    print(json.dumps(json.loads(result["body"]), indent=2))