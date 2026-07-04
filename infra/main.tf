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