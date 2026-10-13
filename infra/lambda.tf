# The four steps run from one container image, each with its own handler. The OCR and extraction
# steps get reserved concurrency: at most model_concurrency calls reach the model server at once.
resource "aws_lambda_function" "step" {
  for_each = local.steps

  function_name = "${local.name}-${each.key}"
  role          = aws_iam_role.step.arn
  package_type  = "Image"
  image_uri     = "${aws_ecr_repository.pipeline.repository_url}:${var.image_tag}"
  architectures = ["arm64"]
  timeout       = each.value.timeout
  memory_size   = each.value.memory
  publish       = true
  kms_key_arn   = aws_kms_key.data.arn

  reserved_concurrent_executions = each.value.concurrency

  image_config {
    command = ["lambdas.handlers.${each.key}"]
  }

  environment {
    variables = {
      DOCUMENTS_BUCKET = aws_s3_bucket.documents.bucket
      RESULTS_TABLE    = aws_dynamodb_table.results.name
      CACHE_TABLE      = aws_dynamodb_table.cache.name
      MODEL_API        = var.model_api
      MODEL_URL        = var.model_url
      OCR_MODEL        = var.ocr_model
      EXTRACTION_MODEL = var.extraction_model
      # The image includes Django for the pipeline's settings; the steps never touch a database.
      DJANGO_SETTINGS_MODULE = "config.settings"
      SECRET_KEY             = "unused-by-lambda-steps"
      RESULT_CACHE_ENABLED   = "true"
      CALLBACK_URL           = local.callback_url
      CALLBACK_SECRET_ARN    = aws_secretsmanager_secret.callback.arn
    }
  }

  tracing_config {
    mode = "Active"
  }

  logging_config {
    log_format = "Text"
    log_group  = aws_cloudwatch_log_group.step[each.key].name
  }

  # Deploys after the first shift code through CodeDeploy (canary on the "live" alias), not Terraform.
  lifecycle {
    ignore_changes = [image_uri]
  }
}

resource "aws_lambda_alias" "live" {
  for_each = local.steps

  name             = "live"
  function_name    = aws_lambda_function.step[each.key].function_name
  function_version = aws_lambda_function.step[each.key].version

  lifecycle {
    ignore_changes = [function_version, routing_config]
  }
}

resource "aws_cloudwatch_log_group" "step" {
  for_each = local.steps

  name              = "/aws/lambda/${local.name}-${each.key}"
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.data.arn
}

resource "aws_iam_role" "step" {
  name               = "${local.name}-step"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role_policy" "step" {
  name   = "pipeline"
  role   = aws_iam_role.step.id
  policy = data.aws_iam_policy_document.step.json
}

data "aws_iam_policy_document" "step" {
  statement {
    sid     = "ReadUploadsAndRules"
    actions = ["s3:GetObject", "s3:GetObjectVersion"]
    resources = [
      "${aws_s3_bucket.documents.arn}/tenants/*",
      "${aws_s3_bucket.documents.arn}/config/rules/*",
      "${aws_s3_bucket.documents.arn}/work/*",
    ]
  }
  statement {
    sid       = "WriteWorkFiles"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.documents.arn}/work/*"]
  }
  statement {
    sid       = "ResultsAndCache"
    actions   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem"]
    resources = [aws_dynamodb_table.results.arn, aws_dynamodb_table.cache.arn]
  }
  statement {
    sid       = "CallbackSecret"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.callback.arn]
  }
  statement {
    sid       = "UseTheDataKey"
    actions   = ["kms:Decrypt", "kms:GenerateDataKey"]
    resources = [aws_kms_key.data.arn]
  }
  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = [for group in aws_cloudwatch_log_group.step : "${group.arn}:*"]
  }
  statement {
    sid       = "Tracing"
    actions   = ["xray:PutTraceSegments", "xray:PutTelemetryRecords"]
    resources = ["*"]
  }
}
