resource "aws_sfn_state_machine" "pipeline" {
  name     = "${local.name}-pipeline"
  role_arn = aws_iam_role.state_machine.arn
  definition = templatefile("${path.module}/statemachine/pipeline.asl.json", {
    prepare_arn           = aws_lambda_alias.live["prepare"].arn
    ocr_arn               = aws_lambda_alias.live["ocr"].arn
    extract_arn           = aws_lambda_alias.live["extract"].arn
    decide_arn            = aws_lambda_alias.live["decide"].arn
    results_table         = aws_dynamodb_table.results.name
    dead_letter_queue_url = aws_sqs_queue.dead_letters.url
    model_retry_seconds   = var.model_retry_seconds
  })

  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.state_machine.arn}:*"
    include_execution_data = false # executions carry receipt contents; keep them out of logs
    level                  = "ERROR"
  }

  tracing_configuration {
    enabled = true
  }

  encryption_configuration {
    type                              = "CUSTOMER_MANAGED_KMS_KEY"
    kms_key_id                        = aws_kms_key.data.arn
    kms_data_key_reuse_period_seconds = 300
  }
}

resource "aws_cloudwatch_log_group" "state_machine" {
  name              = "/aws/vendedlogs/states/${local.name}-pipeline"
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.data.arn
}

resource "aws_iam_role" "state_machine" {
  name               = "${local.name}-state-machine"
  assume_role_policy = data.aws_iam_policy_document.states_assume.json
}

data "aws_iam_policy_document" "states_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["states.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
  }
}

resource "aws_iam_role_policy" "state_machine" {
  name   = "run-pipeline"
  role   = aws_iam_role.state_machine.id
  policy = data.aws_iam_policy_document.state_machine.json
}

data "aws_iam_policy_document" "state_machine" {
  statement {
    sid       = "InvokeSteps"
    actions   = ["lambda:InvokeFunction"]
    resources = [for alias in aws_lambda_alias.live : alias.arn]
  }
  statement {
    sid       = "MarkFailed"
    actions   = ["dynamodb:UpdateItem"]
    resources = [aws_dynamodb_table.results.arn]
  }
  statement {
    sid       = "DeadLetter"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.dead_letters.arn]
  }
  statement {
    sid       = "Encryption"
    actions   = ["kms:Decrypt", "kms:GenerateDataKey"]
    resources = [aws_kms_key.data.arn]
  }
  statement {
    sid = "Logging"
    actions = [
      "logs:CreateLogDelivery", "logs:GetLogDelivery", "logs:UpdateLogDelivery", "logs:DeleteLogDelivery",
      "logs:ListLogDeliveries", "logs:PutResourcePolicy", "logs:DescribeResourcePolicies", "logs:DescribeLogGroups",
    ]
    resources = ["*"]
  }
  statement {
    sid       = "Tracing"
    actions   = ["xray:PutTraceSegments", "xray:PutTelemetryRecords", "xray:GetSamplingRules", "xray:GetSamplingTargets"]
    resources = ["*"]
  }
}
