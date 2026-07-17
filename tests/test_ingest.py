import base64
import importlib
import io
import json
import os
import sys
import unittest
from contextlib import redirect_stdout
from decimal import Decimal
from unittest.mock import Mock, patch

from botocore.exceptions import ClientError


os.environ["QUEUE_URL"] = "https://sqs.example.test/readings"
os.environ["TABLE_NAME"] = "readings"

with patch("boto3.client", return_value=Mock()), patch(
    "boto3.resource", return_value=Mock()
):
    sys.modules.pop("src.ingest", None)
    ingest = importlib.import_module("src.ingest")


class IngestHandlerTests(unittest.TestCase):
    def setUp(self):
        ingest.sqs.reset_mock(return_value=True, side_effect=True)
        ingest.table.reset_mock(return_value=True, side_effect=True)

    @staticmethod
    def event(body, content_type="application/json", is_base64_encoded=False):
        return {
            "headers": {"content-type": content_type},
            "body": body,
            "isBase64Encoded": is_base64_encoded,
        }

    @staticmethod
    def valid_reading():
        return {
            "machine_id": "machine-007",
            "temperature_f": 96.0,
            "vibration_mm_s": 0.1,
            "pressure_psi": 55.0,
            "rpm": 1700,
        }

    @staticmethod
    def get_event(query=None):
        return {
            "requestContext": {"http": {"method": "GET"}},
            "queryStringParameters": query,
        }

    def test_get_readings_queries_machine_in_reverse_time_order(self):
        ingest.table.query.return_value = {
            "Items": [
                {
                    "machine_id": "machine-007",
                    "timestamp": "2026-07-16T19:00:00+00:00",
                    "temperature_f": Decimal("82.5"),
                }
            ]
        }

        result = ingest.lambda_handler(
            self.get_event({"machine_id": "machine-007", "limit": "10"}), None
        )

        self.assertEqual(result["statusCode"], 200)
        body = json.loads(result["body"])
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["readings"][0]["machine_id"], "machine-007")
        ingest.table.query.assert_called_once_with(
            KeyConditionExpression="machine_id = :machine_id",
            ExpressionAttributeValues={":machine_id": "machine-007"},
            Limit=10,
            ScanIndexForward=False,
        )

    def test_get_readings_requires_machine_id(self):
        result = ingest.lambda_handler(self.get_event(), None)

        self.assertEqual(result["statusCode"], 422)
        details = json.loads(result["body"])["details"]
        self.assertEqual(details[0]["field"], "machine_id")
        ingest.table.query.assert_not_called()

    def test_get_readings_returns_503_when_dynamodb_is_unavailable(self):
        ingest.table.query.side_effect = ClientError(
            {"Error": {"Code": "ServiceUnavailable", "Message": "try later"}},
            "Query",
        )

        with redirect_stdout(io.StringIO()):
            result = ingest.lambda_handler(
                self.get_event({"machine_id": "machine-007"}), None
            )

        self.assertEqual(result["statusCode"], 503)
        self.assertEqual(json.loads(result["body"])["error"], "readings_unavailable")

    def test_valid_reading_is_queued(self):
        result = ingest.lambda_handler(
            self.event(json.dumps(self.valid_reading())),
            None,
        )

        self.assertEqual(result["statusCode"], 202)
        response_body = json.loads(result["body"])
        self.assertEqual(response_body["status"], "queued")
        self.assertEqual(response_body["reading"]["severity"], "high")
        ingest.sqs.send_message.assert_called_once()

        queued = json.loads(ingest.sqs.send_message.call_args.kwargs["MessageBody"])
        self.assertEqual(queued["machine_id"], "machine-007")
        self.assertIn("reading_id", queued)
        self.assertIn("timestamp", queued)
        self.assertIn("ingested_at", queued)

    def test_explicit_timestamp_is_preserved_as_event_time(self):
        reading = self.valid_reading()
        reading["timestamp"] = "2026-07-16T12:00:00-07:00"

        result = ingest.lambda_handler(self.event(json.dumps(reading)), None)

        self.assertEqual(result["statusCode"], 202)
        queued = json.loads(ingest.sqs.send_message.call_args.kwargs["MessageBody"])
        self.assertEqual(queued["timestamp"], "2026-07-16T19:00:00+00:00")
        self.assertIn("ingested_at", queued)
        self.assertNotEqual(queued["timestamp"], queued["ingested_at"])

    def test_retry_queues_the_same_natural_key_twice(self):
        reading = self.valid_reading()
        reading["timestamp"] = "2026-07-16T19:00:00Z"
        event = self.event(json.dumps(reading))

        first = ingest.lambda_handler(event, None)
        second = ingest.lambda_handler(event, None)

        self.assertEqual(first["statusCode"], 202)
        self.assertEqual(second["statusCode"], 202)
        queued = [
            json.loads(call.kwargs["MessageBody"])
            for call in ingest.sqs.send_message.call_args_list
        ]
        self.assertEqual(len(queued), 2)
        self.assertEqual(
            (queued[0]["machine_id"], queued[0]["timestamp"]),
            (queued[1]["machine_id"], queued[1]["timestamp"]),
        )
        self.assertNotEqual(queued[0]["reading_id"], queued[1]["reading_id"])

    def test_client_cannot_set_ingested_at(self):
        reading = self.valid_reading()
        reading["ingested_at"] = "2026-07-16T19:00:00Z"

        result = ingest.lambda_handler(self.event(json.dumps(reading)), None)

        self.assertEqual(result["statusCode"], 422)
        details = json.loads(result["body"])["details"]
        self.assertEqual(details[0]["field"], "ingested_at")
        ingest.sqs.send_message.assert_not_called()

    def test_base64_body_is_supported(self):
        encoded = base64.b64encode(
            json.dumps(self.valid_reading()).encode("utf-8")
        ).decode("ascii")

        result = ingest.lambda_handler(self.event(encoded, is_base64_encoded=True), None)

        self.assertEqual(result["statusCode"], 202)

    def test_invalid_json_returns_400(self):
        result = ingest.lambda_handler(self.event("not-json"), None)

        self.assertEqual(result["statusCode"], 400)
        self.assertEqual(
            json.loads(result["body"])["error"],
            "request_body_must_be_valid_json",
        )
        ingest.sqs.send_message.assert_not_called()

    def test_non_json_content_type_returns_415(self):
        result = ingest.lambda_handler(
            self.event(json.dumps(self.valid_reading()), "text/plain"),
            None,
        )

        self.assertEqual(result["statusCode"], 415)
        ingest.sqs.send_message.assert_not_called()

    def test_invalid_fields_return_structured_422(self):
        reading = self.valid_reading()
        reading["rpm"] = -1
        reading["unexpected"] = "field"

        result = ingest.lambda_handler(self.event(json.dumps(reading)), None)

        self.assertEqual(result["statusCode"], 422)
        response_body = json.loads(result["body"])
        self.assertEqual(response_body["error"], "validation_failed")
        self.assertEqual(
            {detail["field"] for detail in response_body["details"]},
            {"rpm", "unexpected"},
        )
        ingest.sqs.send_message.assert_not_called()

    def test_array_body_is_rejected(self):
        result = ingest.lambda_handler(
            self.event(json.dumps([self.valid_reading()])),
            None,
        )

        self.assertEqual(result["statusCode"], 422)
        ingest.sqs.send_message.assert_not_called()

    def test_timestamp_requires_timezone(self):
        reading = self.valid_reading()
        reading["timestamp"] = "2026-07-16T12:00:00"

        result = ingest.lambda_handler(self.event(json.dumps(reading)), None)

        self.assertEqual(result["statusCode"], 422)
        details = json.loads(result["body"])["details"]
        self.assertEqual(details[0]["field"], "timestamp")

    def test_queue_failure_returns_503(self):
        ingest.sqs.send_message.side_effect = ClientError(
            {"Error": {"Code": "ServiceUnavailable", "Message": "try later"}},
            "SendMessage",
        )

        with redirect_stdout(io.StringIO()):
            result = ingest.lambda_handler(
                self.event(json.dumps(self.valid_reading())),
                None,
            )

        self.assertEqual(result["statusCode"], 503)
        self.assertEqual(json.loads(result["body"])["error"], "queue_unavailable")


if __name__ == "__main__":
    unittest.main()
