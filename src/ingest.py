import base64
import json
import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import boto3
from botocore.exceptions import ClientError
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


sqs = boto3.client("sqs")
dynamodb = boto3.resource("dynamodb")

QUEUE_URL = os.environ["QUEUE_URL"]
TABLE_NAME = os.environ["TABLE_NAME"]
table = dynamodb.Table(TABLE_NAME)


class ReadingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    machine_id: str = Field(min_length=1, max_length=100)
    timestamp: datetime | None = None
    temperature_f: float = Field(allow_inf_nan=False)
    vibration_mm_s: float = Field(ge=0, allow_inf_nan=False)
    pressure_psi: float = Field(ge=0, allow_inf_nan=False)
    rpm: int = Field(ge=0)

    @field_validator("timestamp")
    @classmethod
    def timestamp_must_include_timezone(cls, value: datetime | None):
        if value is not None and value.tzinfo is None:
            raise ValueError("timestamp must include a timezone")
        return value


class ReadingQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    machine_id: str = Field(min_length=1, max_length=100)
    limit: int = Field(default=25, ge=1, le=100)


def derive_severity(temperature: float, vibration: float) -> str:
    if temperature >= 95 or vibration >= 0.25:
        return "high"
    if temperature >= 88 or vibration >= 0.18:
        return "medium"
    return "low"


def response(status_code: int, body: dict) -> dict:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body, default=json_default),
    }


def json_default(value):
    if isinstance(value, Decimal):
        return int(value) if value % 1 == 0 else float(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def validation_details(error: ValidationError) -> list[dict]:
    return [
        {
            "field": ".".join(str(part) for part in issue["loc"]),
            "message": issue["msg"],
            "type": issue["type"],
        }
        for issue in error.errors()
    ]


def get_readings(event):
    try:
        query = ReadingQuery.model_validate(event.get("queryStringParameters") or {})
    except ValidationError as error:
        return response(
            422,
            {"error": "validation_failed", "details": validation_details(error)},
        )

    try:
        result = table.query(
            KeyConditionExpression="machine_id = :machine_id",
            ExpressionAttributeValues={":machine_id": query.machine_id},
            Limit=query.limit,
            ScanIndexForward=False,
        )
    except ClientError as error:
        print(f"Failed to read readings: {error.response['Error']['Code']}")
        return response(503, {"error": "readings_unavailable"})

    readings = result.get("Items", [])
    return response(200, {"readings": readings, "count": len(readings)})


def post_reading(event):
    headers = {key.lower(): value for key, value in (event.get("headers") or {}).items()}
    content_type = headers.get("content-type", "").split(";", 1)[0].strip().lower()

    if content_type != "application/json":
        return response(415, {"error": "content_type_must_be_application_json"})

    body = event.get("body") or ""
    if event.get("isBase64Encoded"):
        try:
            body = base64.b64decode(body, validate=True).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return response(400, {"error": "request_body_must_be_valid_json"})

    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, TypeError):
        return response(400, {"error": "request_body_must_be_valid_json"})

    try:
        submitted = ReadingRequest.model_validate(payload)
    except ValidationError as error:
        return response(
            422,
            {
                "error": "validation_failed",
                "details": validation_details(error),
            },
        )

    ingested_at = datetime.now(timezone.utc)
    timestamp = submitted.timestamp or ingested_at
    reading = {
        "reading_id": str(uuid.uuid4()),
        "machine_id": submitted.machine_id,
        "timestamp": timestamp.astimezone(timezone.utc).isoformat(),
        "ingested_at": ingested_at.isoformat(),
        "temperature_f": submitted.temperature_f,
        "vibration_mm_s": submitted.vibration_mm_s,
        "pressure_psi": submitted.pressure_psi,
        "rpm": submitted.rpm,
        "severity": derive_severity(
            submitted.temperature_f,
            submitted.vibration_mm_s,
        ),
    }

    try:
        sqs.send_message(QueueUrl=QUEUE_URL, MessageBody=json.dumps(reading))
    except ClientError as error:
        print(f"Failed to queue reading: {error.response['Error']['Code']}")
        return response(503, {"error": "queue_unavailable"})

    return response(202, {"status": "queued", "reading": reading})


def lambda_handler(event, context):
    method = event.get("requestContext", {}).get("http", {}).get("method", "POST")

    if method == "GET":
        return get_readings(event)
    if method == "POST":
        return post_reading(event)
    return response(405, {"error": "method_not_allowed"})
