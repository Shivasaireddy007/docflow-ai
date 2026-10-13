# New code reaches the "live" alias as a canary: 10% of invocations for 5 minutes, then all of
# them, rolled back automatically if the step's error alarm fires.
resource "aws_codedeploy_app" "pipeline" {
  name             = "${local.name}-pipeline"
  compute_platform = "Lambda"
}

resource "aws_codedeploy_deployment_group" "step" {
  for_each = local.steps

  app_name               = aws_codedeploy_app.pipeline.name
  deployment_group_name  = each.key
  service_role_arn       = aws_iam_role.codedeploy.arn
  deployment_config_name = "CodeDeployDefault.LambdaCanary10Percent5Minutes"

  deployment_style {
    deployment_option = "WITH_TRAFFIC_CONTROL"
    deployment_type   = "BLUE_GREEN"
  }

  alarm_configuration {
    enabled = true
    alarms  = [aws_cloudwatch_metric_alarm.step_errors[each.key].alarm_name]
  }

  auto_rollback_configuration {
    enabled = true
    events  = ["DEPLOYMENT_FAILURE", "DEPLOYMENT_STOP_ON_ALARM"]
  }
}

resource "aws_iam_role" "codedeploy" {
  name = "${local.name}-codedeploy"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "codedeploy.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "codedeploy" {
  role       = aws_iam_role.codedeploy.name
  policy_arn = "arn:${local.partition}:iam::aws:policy/service-role/AWSCodeDeployRoleForLambdaLimited"
}
