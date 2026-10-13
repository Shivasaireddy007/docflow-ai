output "documents_bucket" {
  description = "Upload to s3://<bucket>/tenants/<tenant>/uploads/<file> to process a document."
  value       = aws_s3_bucket.documents.bucket
}

output "results_table" {
  value = aws_dynamodb_table.results.name
}

output "state_machine_arn" {
  value = aws_sfn_state_machine.pipeline.arn
}

output "ecr_repository_url" {
  value = aws_ecr_repository.pipeline.repository_url
}

output "deploy_role_arn" {
  description = "Set as the AWS_DEPLOY_ROLE_ARN secret for the deploy workflow."
  value       = aws_iam_role.deploy.arn
}

output "dead_letter_queue_url" {
  value = aws_sqs_queue.dead_letters.url
}
