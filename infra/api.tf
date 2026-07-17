data "archive_file" "ingest_zip" {
  type        = "zip"
  source_file = "${path.module}/../src/ingest.py"
  output_path = "${path.module}/ingest.zip"
}

resource "aws_lambda_function" "ingest" {
  function_name = "aws-ingestion-api-ingest"
  role          = aws_iam_role.ingest_lambda_role.arn
  runtime       = "python3.11"
  handler       = "ingest.lambda_handler"
  filename      = data.archive_file.ingest_zip.output_path
  architectures = ["x86_64"]

  source_code_hash = data.archive_file.ingest_zip.output_base64sha256
  timeout          = 10

  # AWS-managed layer containing Pydantic for Python 3.11 on x86_64.
  layers = [
    "arn:aws:lambda:us-east-1:017000801446:layer:AWSLambdaPowertoolsPythonV3-python311-x86_64:27"
  ]

  environment {
    variables = {
      QUEUE_URL  = aws_sqs_queue.readings_queue.url
      TABLE_NAME = aws_dynamodb_table.readings.name
    }
  }
}

resource "aws_cloudwatch_log_group" "ingest" {
  name              = "/aws/lambda/aws-ingestion-api-ingest"
  retention_in_days = 7
}

resource "aws_apigatewayv2_api" "ingest" {
  name          = "aws-ingestion-api"
  protocol_type = "HTTP"
}

resource "aws_apigatewayv2_integration" "ingest" {
  api_id                 = aws_apigatewayv2_api.ingest.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.ingest.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "post_readings" {
  api_id    = aws_apigatewayv2_api.ingest.id
  route_key = "POST /readings"
  target    = "integrations/${aws_apigatewayv2_integration.ingest.id}"
}

resource "aws_apigatewayv2_route" "get_readings" {
  api_id    = aws_apigatewayv2_api.ingest.id
  route_key = "GET /readings"
  target    = "integrations/${aws_apigatewayv2_integration.ingest.id}"
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.ingest.id
  name        = "$default"
  auto_deploy = true

  # Public endpoint with no auth - keep the throttle tight to reduce accidental load.
  # API Gateway documents throttles as best-effort targets, not hard cost ceilings.
  default_route_settings {
    throttling_rate_limit  = 2
    throttling_burst_limit = 5
  }
}

resource "aws_lambda_permission" "allow_apigateway_ingest" {
  statement_id  = "AllowApiGatewayInvokeIngest"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ingest.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.ingest.execution_arn}/*/POST/readings"
}

resource "aws_lambda_permission" "allow_apigateway_readings" {
  statement_id  = "AllowApiGatewayReadings"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ingest.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.ingest.execution_arn}/*/GET/readings"
}
