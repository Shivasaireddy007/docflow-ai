# Every upload under tenants/<tenant>/uploads/ starts an execution with {bucket, key}.
resource "aws_cloudwatch_event_rule" "upload" {
  name        = "${local.name}-upload"
  description = "A document was uploaded for processing"
  event_pattern = jsonencode({
    source      = ["aws.s3"]
    detail-type = ["Object Created"]
    detail = {
      bucket = { name = [aws_s3_bucket.documents.bucket] }
      object = { key = [{ wildcard = "tenants/*/uploads/*" }] }
    }
  })
}

resource "aws_cloudwatch_event_target" "upload" {
  rule     = aws_cloudwatch_event_rule.upload.name
  arn      = aws_sfn_state_machine.pipeline.arn
  role_arn = aws_iam_role.events.arn

  input_transformer {
    input_paths = {
      bucket = "$.detail.bucket.name"
      key    = "$.detail.object.key"
    }
    input_template = "{\"bucket\": <bucket>, \"key\": <key>}"
  }

  retry_policy {
    maximum_event_age_in_seconds = 3600
    maximum_retry_attempts       = 10
  }

  dead_letter_config {
    arn = aws_sqs_queue.dead_letters.arn
  }
}

resource "aws_iam_role" "events" {
  name = "${local.name}-events"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "events.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "events" {
  name = "start-pipeline"
  role = aws_iam_role.events.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "states:StartExecution"
      Resource = aws_sfn_state_machine.pipeline.arn
    }]
  })
}

# EventBridge also sends events it couldn't deliver to the dead-letter queue.
resource "aws_sqs_queue_policy" "dead_letters" {
  queue_url = aws_sqs_queue.dead_letters.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "events.amazonaws.com" }
      Action    = "sqs:SendMessage"
      Resource  = aws_sqs_queue.dead_letters.arn
      Condition = { ArnEquals = { "aws:SourceArn" = aws_cloudwatch_event_rule.upload.arn } }
    }]
  })
}
