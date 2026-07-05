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

  tags = {
    Project = "aws-ingestion"
  }
}

resource "aws_sqs_queue" "readings_dlq" {
  name = "aws-ingestion-readings-dlq"

  tags = {
    Project = "aws-ingestion"
  }
}

resource "aws_sqs_queue" "readings_queue" {
  name                       = "aws-ingestion-readings-queue"
  visibility_timeout_seconds = 30
  message_retention_seconds  = 345600

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.readings_dlq.arn
    maxReceiveCount     = 3
  })

  tags = {
    Project = "aws-ingestion"
  }
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

  tags = {
    Project = "aws-ingestion"
  }
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

  tags = {
    Project = "aws-ingestion"
  }
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

  tags = {
    Project = "aws-ingestion"
  }
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

  timeout = 10

  environment {
    variables = {
      TABLE_NAME = aws_dynamodb_table.readings.name
    }
  }

  tags = {
    Project = "aws-ingestion"
  }
}

resource "aws_lambda_event_source_mapping" "readings_queue_to_writer" {
  event_source_arn        = aws_sqs_queue.readings_queue.arn
  function_name           = aws_lambda_function.writer.arn
  batch_size              = 10
  function_response_types = ["ReportBatchItemFailures"]
}