# aws-ingestion

Small AWS ingestion pipeline for machine readings.

It generates machine telemetry, sends readings through SQS, writes them to DynamoDB, and can send a Discord alert when a high-severity reading comes in.

## Architecture

```text
EventBridge schedule
  -> generator Lambda
  -> SQS queue
  -> writer Lambda
  -> DynamoDB
  -> optional Discord webhook alert
```

The Discord webhook URL is stored in Secrets Manager. It is not hardcoded in the Lambda code or committed to the repo.

## Resources

Terraform creates:

- DynamoDB table: `aws-ingestion-readings`
- SQS queue: `aws-ingestion-readings-queue`
- SQS DLQ: `aws-ingestion-readings-dlq`
- generator Lambda: `aws-ingestion-generator`
- writer Lambda: `aws-ingestion-writer`
- EventBridge schedule: disabled by default
- Secrets Manager secret: `aws-ingestion/discord-webhook`

## Deploy

From `infra/`:

```powershell
terraform init
terraform apply
```

The generator schedule is disabled by default. To run the generator on a timer, change the EventBridge rule state to `ENABLED` in `infra/main.tf`, apply, and switch it back to `DISABLED` when testing is done.

## Discord alerts

Set the webhook secret after Terraform creates it:

```powershell
aws secretsmanager put-secret-value `
  --region us-east-1 `
  --secret-id aws-ingestion/discord-webhook `
  --secret-string "https://discord.com/api/webhooks/..."
```

The writer accepts either a raw URL:

```text
https://discord.com/api/webhooks/...
```

or JSON:

```json
{"url":"https://discord.com/api/webhooks/..."}
```

Only readings with `"severity": "high"` send Discord alerts. Alert failures are logged but do not fail ingestion.

## Test a high-severity alert

Send a high-severity message directly to SQS:

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

Then check:

- DynamoDB for the inserted reading
- Discord for the alert
