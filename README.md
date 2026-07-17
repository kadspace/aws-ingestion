# aws-ingestion

Event-driven AWS ingestion pipeline for simulated machine telemetry.

The project generates fake machine readings, buffers them through SQS, stores them in DynamoDB, and sends an optional Discord alert when a high-severity reading comes in. Infrastructure is defined with Terraform and the Lambda handlers are written in Python.

## Architecture

![aws-ingestion architecture](docs/assets/architecture.png)

The main path is intentionally small: EventBridge can trigger a generator Lambda, while API Gateway accepts submitted readings through a separate ingest Lambda. Both paths send one SQS message per reading, and a writer Lambda persists every reading to DynamoDB. Discord alerts are a side path from the writer Lambda and only run for high-severity readings.

## AWS Resources

Terraform creates:

- DynamoDB table: `aws-ingestion-readings`
- SQS queue: `aws-ingestion-readings-queue`
- SQS DLQ: `aws-ingestion-readings-dlq`
- Generator Lambda: `aws-ingestion-generator`
- API ingest Lambda: `aws-ingestion-api-ingest`
- API Gateway HTTP API: `POST /readings`, `GET /readings`
- Writer Lambda: `aws-ingestion-writer`
- EventBridge schedule: disabled by default
- Secrets Manager secret: `aws-ingestion/discord-webhook`

## Deploy

From `infra`:

```powershell
terraform init
terraform apply
```

Terraform prints the API base URL as `api_endpoint`. Submit one reading with:

```powershell
$api = terraform output -raw api_endpoint

curl.exe -X POST "$api/readings" `
  -H "Content-Type: application/json" `
  --data-binary '{"machine_id":"machine-007","timestamp":"2026-07-16T19:00:00Z","temperature_f":82,"vibration_mm_s":0.1,"pressure_psi":55,"rpm":1700}'
```

A queued reading returns `202`; malformed or invalid requests return `400`, `415`, or `422`.

Read the newest stored readings for one machine with:

```powershell
curl.exe "$api/readings?machine_id=machine-007&limit=25"
```

`machine_id` is required; `limit` accepts 1 through 100 (default 25). Results are ordered newest first.

## Data model

Example reading:

```json
{
  "reading_id": "discord-test-001",
  "machine_id": "machine-999",
  "timestamp": "2026-07-05T21:10:00Z",
  "temperature_f": 101.5,
  "vibration_mm_s": 0.31,
  "pressure_psi": 59.2,
  "rpm": 1880,
  "severity": "high"
}
```

The DynamoDB key is the natural key `(machine_id, timestamp)` and writes are first-write-wins: a retried reading returns `202` again (the API's `202` means "accepted into SQS"), and the writer's conditional write skips the duplicate. `timestamp` is event time supplied by the client, defaulted to the current time if omitted; the ingest Lambda also adds a server-owned `ingested_at`, so the gap between the two shows device buffering or pipeline lag. `reading_id` exists for traceability and is not the deduplication key.

## Tests

The `tests` directory contains unit tests for the ingest and writer Lambdas with AWS calls mocked. Run them from the repository root:

```powershell
python -m unittest discover -s tests -v
```

## Scheduled generation

The EventBridge schedule is disabled by default so the project does not keep producing data. To run the generator on a timer, set `state = "ENABLED"` on the rule in `infra/main.tf` and `terraform apply`; switch it back to `DISABLED` and apply again when done.

## Discord alerts

Set the webhook secret after Terraform creates it:

```powershell
aws secretsmanager put-secret-value `
  --region us-east-1 `
  --secret-id aws-ingestion/discord-webhook `
  --secret-string "https://discord.com/api/webhooks/..."
```

The secret can be a raw webhook URL or a JSON object like `{"url":"..."}`. Only high-severity readings trigger an alert, and alert failures are logged without failing ingestion.

## Test a high-severity alert

Send a known high-severity message directly to SQS:

```powershell
$queueUrl = aws sqs get-queue-url `
  --region us-east-1 `
  --queue-name aws-ingestion-readings-queue `
  --query QueueUrl `
  --output text

aws sqs send-message `
  --region us-east-1 `
  --queue-url $queueUrl `
  --message-body '{"reading_id":"discord-test-001","machine_id":"machine-999","timestamp":"2026-07-05T21:10:00Z","temperature_f":101.5,"vibration_mm_s":0.31,"pressure_psi":59.2,"rpm":1880,"severity":"high"}'
```

Then check DynamoDB for the inserted reading, Discord for the alert, and the CloudWatch logs for `/aws/lambda/aws-ingestion-writer`.

## Cost and cleanup

Leave the schedule `DISABLED` whenever you are not actively testing — it is the one thing that keeps generating readings and costs. With the schedule disabled, the only meaningful standing cost is the Secrets Manager secret, roughly cents per day; light testing keeps Lambda, SQS, and logs within typical free-tier usage. Remove the AWS resources with:

```powershell
terraform destroy
```

## Design Sketches

The final version started as a quick hand-drawn event flow, then got cleaned up into a more readable sketch before the Terraform and Lambda wiring settled.

<table>
  <tr>
    <td width="50%">
      <img src="docs/assets/sketch-original.png" alt="Original handwritten architecture sketch">
    </td>
    <td width="50%">
      <img src="docs/assets/sketch-readable.png" alt="Readable architecture sketch">
    </td>
  </tr>
  <tr>
    <td align="center">Original sketch</td>
    <td align="center">Readable sketch</td>
  </tr>
</table>
