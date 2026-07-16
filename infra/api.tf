resource "aws_apigatewayv2_api" "ingest" {
  name          = "aws-ingestion-api"
  protocol_type = "HTTP"
}

resource "aws_apigatewayv2_integration" "generator" {
  api_id                 = aws_apigatewayv2_api.ingest.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.generator.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "post_readings" {
  api_id    = aws_apigatewayv2_api.ingest.id
  route_key = "POST /readings"
  target    = "integrations/${aws_apigatewayv2_integration.generator.id}"
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.ingest.id
  name        = "$default"
  auto_deploy = true

  # Public endpoint with no auth - keep the throttle tight to cap abuse cost
  default_route_settings {
    throttling_rate_limit  = 2
    throttling_burst_limit = 5
  }
}

resource "aws_lambda_permission" "allow_apigateway_generator" {
  statement_id  = "AllowApiGatewayInvokeGenerator"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.generator.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.ingest.execution_arn}/*/*"
}
