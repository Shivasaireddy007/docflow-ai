# SLO alarms. They notify the alarm topic, and the Lambda error alarms also roll back a canary.
resource "aws_sns_topic" "alarms" {
  name              = "${local.name}-alarms"
  kms_master_key_id = aws_kms_key.data.id
}

resource "aws_sns_topic_subscription" "email" {
  count     = var.alarm_email == "" ? 0 : 1
  topic_arn = aws_sns_topic.alarms.arn
  protocol  = "email"
  endpoint  = var.alarm_email
}

resource "aws_cloudwatch_metric_alarm" "slo_latency" {
  alarm_name          = "${local.name}-p95-upload-to-decision"
  alarm_description   = "SLO: 95% of documents decided within ${var.document_slo_ms / 1000} s of upload."
  namespace           = "AWS/States"
  metric_name         = "ExecutionTime"
  dimensions          = { StateMachineArn = aws_sfn_state_machine.pipeline.arn }
  extended_statistic  = "p95"
  period              = 300
  evaluation_periods  = 3
  datapoints_to_alarm = 2
  threshold           = var.document_slo_ms
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
  ok_actions          = [aws_sns_topic.alarms.arn]
}

resource "aws_cloudwatch_metric_alarm" "failed_documents" {
  alarm_name          = "${local.name}-failed-documents"
  alarm_description   = "Documents ended in the dead-letter queue."
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = aws_sqs_queue.dead_letters.name }
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
}

resource "aws_cloudwatch_metric_alarm" "step_errors" {
  for_each = local.steps

  alarm_name          = "${local.name}-${each.key}-errors"
  alarm_description   = "The ${each.key} step is failing; also rolls back a canary deploy of it."
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.step[each.key].function_name, Resource = "${aws_lambda_function.step[each.key].function_name}:live" }
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 2
  threshold           = 2
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
}

resource "aws_cloudwatch_metric_alarm" "model_throttled" {
  for_each = { for k, v in local.steps : k => v if v.concurrency != null }

  alarm_name          = "${local.name}-${each.key}-throttled"
  alarm_description   = "${each.key} is at its concurrency limit: documents are queueing for the model."
  namespace           = "AWS/Lambda"
  metric_name         = "Throttles"
  dimensions          = { FunctionName = aws_lambda_function.step[each.key].function_name }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 3
  threshold           = 10
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
}
