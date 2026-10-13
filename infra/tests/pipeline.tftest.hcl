# Runs the whole configuration against a mocked AWS provider (no account, no cost) and checks the
# properties that matter: encryption, isolation from the internet, retries, limits and alarms.
#   terraform test

mock_provider "aws" {
  mock_data "aws_caller_identity" {
    defaults = { account_id = "123456789012" }
  }
  mock_data "aws_partition" {
    defaults = { partition = "aws" }
  }
  mock_data "aws_iam_policy_document" {
    defaults = { json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}" }
  }
  mock_resource "aws_lambda_alias" {
    defaults = { arn = "arn:aws:lambda:ap-south-1:123456789012:function:docflow-demo-step:live" }
  }
  mock_resource "aws_lambda_function" {
    defaults = { arn = "arn:aws:lambda:ap-south-1:123456789012:function:docflow-demo-step", version = "1" }
  }
  mock_resource "aws_sns_topic" {
    defaults = { arn = "arn:aws:sns:ap-south-1:123456789012:docflow-demo-alarms" }
  }
  mock_resource "aws_kms_key" {
    defaults = { arn = "arn:aws:kms:ap-south-1:123456789012:key/1234abcd-12ab-34cd-56ef-1234567890ab", key_id = "1234abcd-12ab-34cd-56ef-1234567890ab" }
  }
  mock_resource "aws_sqs_queue" {
    defaults = { arn = "arn:aws:sqs:ap-south-1:123456789012:docflow-demo-dead-letters", url = "https://sqs.ap-south-1.amazonaws.com/123456789012/docflow-demo-dead-letters", id = "https://sqs.ap-south-1.amazonaws.com/123456789012/docflow-demo-dead-letters" }
  }
  mock_resource "aws_iam_role" {
    defaults = { arn = "arn:aws:iam::123456789012:role/docflow-demo" }
  }
  mock_resource "aws_cloudwatch_log_group" {
    defaults = { arn = "arn:aws:logs:ap-south-1:123456789012:log-group:docflow-demo" }
  }
  mock_resource "aws_dynamodb_table" {
    defaults = { arn = "arn:aws:dynamodb:ap-south-1:123456789012:table/docflow-demo" }
  }
  mock_resource "aws_s3_bucket" {
    defaults = { arn = "arn:aws:s3:::docflow-demo-documents", bucket = "docflow-demo-documents", id = "docflow-demo-documents" }
  }
  mock_resource "aws_sfn_state_machine" {
    defaults = { arn = "arn:aws:states:ap-south-1:123456789012:stateMachine:docflow-demo-pipeline" }
  }
  mock_resource "aws_cloudwatch_event_rule" {
    defaults = { arn = "arn:aws:events:ap-south-1:123456789012:rule/docflow-demo-upload" }
  }
  mock_resource "aws_iam_openid_connect_provider" {
    defaults = { arn = "arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com" }
  }
  mock_resource "aws_secretsmanager_secret" {
    defaults = { arn = "arn:aws:secretsmanager:ap-south-1:123456789012:secret:docflow-demo-callback-AbCdEf", id = "arn:aws:secretsmanager:ap-south-1:123456789012:secret:docflow-demo-callback-AbCdEf" }
  }
  mock_resource "aws_iam_policy" {
    defaults = { arn = "arn:aws:iam::123456789012:policy/docflow-demo-review-app" }
  }
  mock_resource "aws_ecr_repository" {
    defaults = { arn = "arn:aws:ecr:ap-south-1:123456789012:repository/docflow-demo-pipeline", repository_url = "123456789012.dkr.ecr.ap-south-1.amazonaws.com/docflow-demo-pipeline" }
  }
}

variables {
  model_url = "http://models.internal:8000"
}

run "data_is_encrypted_and_private" {
  command = apply

  assert {
    condition     = one(aws_s3_bucket_server_side_encryption_configuration.documents.rule).apply_server_side_encryption_by_default[0].sse_algorithm == "aws:kms"
    error_message = "Documents must be encrypted with the customer-managed key."
  }
  assert {
    condition = alltrue([
      aws_s3_bucket_public_access_block.documents.block_public_acls,
      aws_s3_bucket_public_access_block.documents.block_public_policy,
      aws_s3_bucket_public_access_block.documents.ignore_public_acls,
      aws_s3_bucket_public_access_block.documents.restrict_public_buckets,
    ])
    error_message = "The documents bucket must never be public."
  }
  assert {
    condition     = aws_kms_key.data.enable_key_rotation
    error_message = "The data key must rotate."
  }
  assert {
    condition     = aws_dynamodb_table.results.point_in_time_recovery[0].enabled && aws_dynamodb_table.results.deletion_protection_enabled
    error_message = "Results need point-in-time recovery and deletion protection."
  }
  assert {
    condition     = aws_dynamodb_table.results.server_side_encryption[0].enabled && aws_dynamodb_table.cache.server_side_encryption[0].enabled
    error_message = "Both tables must be encrypted with the customer-managed key."
  }
  assert {
    condition     = aws_sqs_queue.dead_letters.kms_master_key_id != null
    error_message = "Failed documents carry receipt data; the queue must be encrypted."
  }
}

run "the_pipeline_protects_the_model_server" {
  command = apply

  assert {
    condition     = aws_lambda_function.step["ocr"].reserved_concurrent_executions == 4 && aws_lambda_function.step["extract"].reserved_concurrent_executions == 4
    error_message = "Model steps must be capped at model_concurrency."
  }
  assert {
    condition     = jsondecode(aws_sfn_state_machine.pipeline.definition).States["OCR"].Retry[0].MaxAttempts == 4
    error_message = "OCR must retry model failures."
  }
  assert {
    condition     = contains(jsondecode(aws_sfn_state_machine.pipeline.definition).States["OCR"].Retry[0].ErrorEquals, "ModelBusy")
    error_message = "A busy model must be retried, not failed."
  }
  assert {
    condition     = !contains(flatten([for r in jsondecode(aws_sfn_state_machine.pipeline.definition).States["Prepare"].Retry : r.ErrorEquals]), "UnsupportedFile")
    error_message = "An unusable upload must not be retried."
  }
  assert {
    condition     = aws_sfn_state_machine.pipeline.logging_configuration[0].include_execution_data == false
    error_message = "Execution data (receipt contents) must stay out of the logs."
  }
}

run "deploys_are_canaries_from_main_only" {
  command = apply

  assert {
    condition     = length(jsondecode(aws_cloudwatch_dashboard.pipeline.dashboard_body).widgets) == 5
    error_message = "The dashboard shows the SLO, documents, step times, errors and decisions."
  }

  assert {
    condition     = alltrue([for g in aws_codedeploy_deployment_group.step : g.deployment_config_name == "CodeDeployDefault.LambdaCanary10Percent5Minutes" && g.auto_rollback_configuration[0].enabled])
    error_message = "Every step deploys as a canary that rolls back on alarm."
  }
  assert {
    condition     = jsondecode(aws_iam_role.deploy.assume_role_policy).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:sub"] == "repo:Shivasaireddy007/docflow-ai:ref:refs/heads/main"
    error_message = "Only the main branch of this repository may deploy."
  }
  assert {
    condition     = aws_cloudwatch_metric_alarm.slo_latency.threshold == 30000 && aws_cloudwatch_metric_alarm.slo_latency.extended_statistic == "p95"
    error_message = "The SLO alarm watches p95 upload-to-decision time against 30 s."
  }
}

run "budget_and_email_only_when_asked" {
  command = apply

  assert {
    condition     = length(aws_budgets_budget.monthly) == 0 && length(aws_sns_topic_subscription.email) == 0
    error_message = "Without an email there is no one to notify."
  }
}

run "budget_with_an_email" {
  command = apply
  variables {
    alarm_email = "ops@example.com"
  }

  assert {
    condition     = length(aws_budgets_budget.monthly) == 1 && aws_budgets_budget.monthly[0].limit_amount == "10"
    error_message = "A monthly budget warns the alarm email."
  }
}

run "unknown_model_apis_are_refused" {
  command = plan
  variables {
    model_api = "bedrock"
  }
  expect_failures = [var.model_api]
}

run "standalone_unless_a_review_app_is_given" {
  command = apply

  assert {
    condition     = aws_lambda_function.step["decide"].environment[0].variables["CALLBACK_URL"] == ""
    error_message = "Without a review app the pipeline decides on its own."
  }
  assert {
    condition     = contains(keys(jsondecode(aws_sfn_state_machine.pipeline.definition).States), "Report failure")
    error_message = "Failures are reported (a no-op when standalone)."
  }
}

run "integrated_with_the_review_app" {
  command = apply
  variables {
    review_app_url = "https://review.example.com/"
  }

  assert {
    condition     = aws_lambda_function.step["decide"].environment[0].variables["CALLBACK_URL"] == "https://review.example.com/api/v1/internal/pipeline-results"
    error_message = "Reports go to the app's callback endpoint."
  }
  assert {
    condition     = aws_secretsmanager_secret.callback.kms_key_id != null && length(random_password.callback.result) == 48
    error_message = "The callback secret is long and encrypted with the data key."
  }
  assert {
    condition     = contains(jsondecode(aws_sfn_state_machine.pipeline.definition).States["Decide"].Retry[0].ErrorEquals, "CallbackError")
    error_message = "A review app that is briefly down is retried."
  }
  assert {
    condition     = jsondecode(aws_iam_policy.review_app.policy).Statement[1].Action == "states:StartExecution"
    error_message = "The review app can start reprocessing and nothing more on the state machine."
  }
}
