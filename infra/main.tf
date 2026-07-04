terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
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