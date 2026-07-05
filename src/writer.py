import json
import os
from decimal import Decimal

import boto3
from botocore.exceptions import ClientError

dynamodb = boto3.resource("dynamodb")
TABLE_NAME = os.environ["TABLE_NAME"]
table = dynamodb.Table(TABLE_NAME)


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

        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                # Duplicate message. Treat as success.
                continue

            failures.append({"itemIdentifier": record["messageId"]})

        except Exception:
            failures.append({"itemIdentifier": record["messageId"]})

    return {
        "batchItemFailures": failures
    }