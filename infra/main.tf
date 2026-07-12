terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }

    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
  }
}

provider "aws" {
  region = "us-east-1"
}

resource "aws_dynamodb_table" "readings" {
  name         = "aws-ingestion-readings"
  billing_mode = "PAY_PER_REQUEST"

  hash_key  = "machine_id"
  range_key = "timestamp"

  attribute {
    name = "machine_id"
    type = "S"
  }

  attribute {
    name = "timestamp"
    type = "S"
  }
}

resource "aws_sqs_queue" "readings_dlq" {
  name = "aws-ingestion-readings-dlq"
}

resource "aws_sqs_queue" "readings_queue" {
  name                       = "aws-ingestion-readings-queue"
  visibility_timeout_seconds = 90
  message_retention_seconds  = 345600

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.readings_dlq.arn
    maxReceiveCount     = 3
  })
}

output "readings_queue_url" {
  value = aws_sqs_queue.readings_queue.url
}

data "archive_file" "generator_zip" {
  type        = "zip"
  source_file = "${path.module}/../src/generator.py"
  output_path = "${path.module}/generator.zip"
}

resource "aws_iam_role" "generator_lambda_role" {
  name = "aws-ingestion-generator-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "generator_basic_execution" {
  role       = aws_iam_role.generator_lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "generator_sqs_policy" {
  name = "aws-ingestion-generator-sqs-policy"
  role = aws_iam_role.generator_lambda_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["sqs:SendMessage"]
        Resource = aws_sqs_queue.readings_queue.arn
      }
    ]
  })
}

resource "aws_lambda_function" "generator" {
  function_name = "aws-ingestion-generator"
  role          = aws_iam_role.generator_lambda_role.arn
  runtime       = "python3.11"
  handler       = "generator.lambda_handler"
  filename      = data.archive_file.generator_zip.output_path

  source_code_hash = data.archive_file.generator_zip.output_base64sha256

  timeout = 10

  environment {
    variables = {
      QUEUE_URL = aws_sqs_queue.readings_queue.url
    }
  }
}

resource "aws_cloudwatch_log_group" "generator" {
  name              = "/aws/lambda/aws-ingestion-generator"
  retention_in_days = 7
}

data "archive_file" "writer_zip" {
  type        = "zip"
  source_file = "${path.module}/../src/writer.py"
  output_path = "${path.module}/writer.zip"
}

resource "aws_iam_role" "writer_lambda_role" {
  name = "aws-ingestion-writer-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "writer_basic_execution" {
  role       = aws_iam_role.writer_lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "writer_sqs_dynamodb_policy" {
  name = "aws-ingestion-writer-sqs-dynamodb-policy"
  role = aws_iam_role.writer_lambda_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:GetQueueAttributes",
          "sqs:ChangeMessageVisibility"
        ]
        Resource = aws_sqs_queue.readings_queue.arn
      },
      {
        Effect = "Allow"
        Action = [
          "dynamodb:PutItem"
        ]
        Resource = aws_dynamodb_table.readings.arn
      },
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue"
        ]
        Resource = aws_secretsmanager_secret.discord_webhook.arn
      }
    ]
  })
}

resource "aws_lambda_function" "writer" {
  function_name = "aws-ingestion-writer"
  role          = aws_iam_role.writer_lambda_role.arn
  runtime       = "python3.11"
  handler       = "writer.lambda_handler"
  filename      = data.archive_file.writer_zip.output_path

  source_code_hash = data.archive_file.writer_zip.output_base64sha256

  timeout = 15

  environment {
    variables = {
      TABLE_NAME        = aws_dynamodb_table.readings.name
      DISCORD_SECRET_ID = aws_secretsmanager_secret.discord_webhook.name
    }
  }
}

resource "aws_cloudwatch_log_group" "writer" {
  name              = "/aws/lambda/aws-ingestion-writer"
  retention_in_days = 7
}

resource "aws_lambda_event_source_mapping" "readings_queue_to_writer" {
  event_source_arn        = aws_sqs_queue.readings_queue.arn
  function_name           = aws_lambda_function.writer.arn
  batch_size              = 5
  function_response_types = ["ReportBatchItemFailures"]
}

resource "aws_cloudwatch_event_rule" "generator_schedule" {
  name                = "aws-ingestion-generator-schedule"
  description         = "Runs the generator Lambda on a schedule"
  schedule_expression = "rate(5 minutes)"
  state               = "DISABLED"
}

resource "aws_cloudwatch_event_target" "generator_schedule_target" {
  rule      = aws_cloudwatch_event_rule.generator_schedule.name
  target_id = "aws-ingestion-generator"
  arn       = aws_lambda_function.generator.arn
}

resource "aws_lambda_permission" "allow_eventbridge_generator" {
  statement_id  = "AllowEventBridgeInvokeGenerator"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.generator.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.generator_schedule.arn
}

resource "aws_secretsmanager_secret" "discord_webhook" {
  name        = "aws-ingestion/discord-webhook"
  description = "Optional Discord webhook URL for high severity alerts"
}

resource "aws_sns_topic" "pipeline_alerts" {
  name = "aws-ingestion-pipeline-alerts"
}

resource "aws_sns_topic_subscription" "email_alert" {
  topic_arn = aws_sns_topic.pipeline_alerts.arn
  protocol  = "email"
  endpoint  = "kacperdudz@gmail.com"
}

resource "aws_cloudwatch_metric_alarm" "dlq_not_empty" {
  alarm_name        = "aws-ingestion-dlq-messages"
  alarm_description = "A message hit the DLQ - 3 real failures on the writer"
  namespace         = "AWS/SQS"
  metric_name       = "ApproximateNumberOfMessagesVisible"
  dimensions = {
    QueueName = aws_sqs_queue.readings_dlq.name
  }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.pipeline_alerts.arn]
}
