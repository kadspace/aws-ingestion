import importlib
import io
import json
import os
import sys
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, patch

from botocore.exceptions import ClientError


os.environ["TABLE_NAME"] = "aws-ingestion-readings"
os.environ["DISCORD_SECRET_ID"] = ""

fake_table = Mock()
fake_dynamodb = Mock()
fake_dynamodb.Table.return_value = fake_table

with (
    patch("boto3.resource", return_value=fake_dynamodb),
    patch("boto3.client", return_value=Mock()),
):
    sys.modules.pop("src.writer", None)
    writer = importlib.import_module("src.writer")


class WriterHandlerTests(unittest.TestCase):
    def setUp(self):
        fake_table.reset_mock(return_value=True, side_effect=True)

    def test_duplicate_natural_key_is_logged_and_skipped(self):
        reading = {
            "reading_id": "first-attempt-id",
            "machine_id": "machine-retry-test",
            "timestamp": "2026-07-16T19:00:00+00:00",
            "ingested_at": "2026-07-16T19:00:01+00:00",
            "temperature_f": 80.0,
            "vibration_mm_s": 0.1,
            "pressure_psi": 55.0,
            "rpm": 1700,
            "severity": "low",
        }
        duplicate_error = ClientError(
            {
                "Error": {
                    "Code": "ConditionalCheckFailedException",
                    "Message": "item already exists",
                }
            },
            "PutItem",
        )
        fake_table.put_item.side_effect = [None, duplicate_error]
        event = {
            "Records": [
                {"messageId": "message-1", "body": json.dumps(reading)},
                {
                    "messageId": "message-2",
                    "body": json.dumps({**reading, "reading_id": "retry-id"}),
                },
            ]
        }

        output = io.StringIO()
        with redirect_stdout(output):
            result = writer.lambda_handler(event, None)

        self.assertEqual(result, {"batchItemFailures": []})
        self.assertEqual(fake_table.put_item.call_count, 2)
        self.assertIn("Duplicate reading skipped", output.getvalue())


if __name__ == "__main__":
    unittest.main()
