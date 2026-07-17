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

resource "aws_iam_role" "ingest_lambda_role" {
  name = "aws-ingestion-api-ingest-lambda-role"

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

resource "aws_iam_role_policy_attachment" "ingest_basic_execution" {
  role       = aws_iam_role.ingest_lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "ingest_sqs_policy" {
  name = "aws-ingestion-api-ingest-sqs-policy"
  role = aws_iam_role.ingest_lambda_role.id

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

resource "aws_iam_role_policy" "ingest_dynamodb_policy" {
  name = "aws-ingestion-api-ingest-dynamodb-policy"
  role = aws_iam_role.ingest_lambda_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["dynamodb:Query"]
        Resource = aws_dynamodb_table.readings.arn
      }
    ]
  })
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
        Effect   = "Allow"
        Action   = ["dynamodb:PutItem"]
        Resource = aws_dynamodb_table.readings.arn
      },
      {
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue"]
        Resource = aws_secretsmanager_secret.discord_webhook.arn
      }
    ]
  })
}
