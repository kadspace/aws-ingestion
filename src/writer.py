import json
import os
from urllib import error, request
from decimal import Decimal

import boto3
from botocore.exceptions import ClientError

dynamodb = boto3.resource("dynamodb")
secretsmanager = boto3.client("secretsmanager")

TABLE_NAME = os.environ["TABLE_NAME"]
DISCORD_SECRET_ID = os.environ.get("DISCORD_SECRET_ID", "")

table = dynamodb.Table(TABLE_NAME)

_cached_discord_webhook_url = None
_discord_secret_loaded = False


def get_discord_webhook_url():
    global _cached_discord_webhook_url, _discord_secret_loaded

    if _discord_secret_loaded or not DISCORD_SECRET_ID:
        return _cached_discord_webhook_url

    try:
        secret_string = (
            secretsmanager.get_secret_value(SecretId=DISCORD_SECRET_ID)
            .get("SecretString", "")
            .strip()
        )
    except ClientError as e:
        print(f"Discord secret unavailable: {e.response['Error']['Code']}")
        return None

    try:
        parsed = json.loads(secret_string)
        if isinstance(parsed, dict):
            secret_string = parsed.get("url", "").strip()
    except json.JSONDecodeError:
        pass

    if not secret_string:
        print("Discord secret is empty")
    elif not secret_string.startswith("https://"):
        print("Discord secret does not look like a webhook URL")
    else:
        _cached_discord_webhook_url = secret_string
        _discord_secret_loaded = True

    return _cached_discord_webhook_url


def send_discord_alert(reading: dict) -> None:
    webhook_url = get_discord_webhook_url()

    if not webhook_url:
        print("Skipping Discord alert: no webhook configured")
        return

    fields = (
        "machine_id",
        "timestamp",
        "temperature_f",
        "vibration_mm_s",
        "pressure_psi",
        "rpm",
        "reading_id",
    )
    field_lines = [f"{field}: {reading.get(field)}" for field in fields]
    message = "\n".join(["High severity machine reading", *field_lines])
    payload = json.dumps({"content": message}).encode("utf-8")

    discord_request = request.Request(
        webhook_url,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "aws-ingestion/1.0"},
        method="POST",
    )

    try:
        with request.urlopen(discord_request, timeout=2) as response:
            print(f"Discord alert sent: status={response.status}")
    except error.HTTPError as e:
        body = e.read(300).decode("utf-8", "replace")
        print(f"Discord alert failed: status={e.code} body={body}")
    except Exception as e:
        print(f"Discord alert failed: {e}")


def lambda_handler(event, context):
    failures = []

    for record in event["Records"]:
        try:
            reading = json.loads(record["body"], parse_float=Decimal)

            table.put_item(
                Item=reading,
                ConditionExpression="attribute_not_exists(machine_id) AND attribute_not_exists(#ts)",
                ExpressionAttributeNames={
                    "#ts": "timestamp"
                },
            )

            print(f"Wrote reading_id={reading.get('reading_id')}")

            if reading.get("severity") == "high":
                send_discord_alert(reading)

        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                print("Duplicate reading skipped")
                continue

            print(f"AWS error: {e}")
            failures.append({"itemIdentifier": record["messageId"]})

        except Exception as e:
            print(f"Unexpected error: {e}")
            failures.append({"itemIdentifier": record["messageId"]})

    return {
        "batchItemFailures": failures
    }
