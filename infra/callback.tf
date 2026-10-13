# The pipeline reports results to the review app over HTTPS, signed with this secret (HMAC-SHA256
# over timestamp and body). The app needs the same value as CALLBACK_SECRET:
#   aws secretsmanager get-secret-value --secret-id <callback_secret_arn> --query SecretString
resource "random_password" "callback" {
  length  = 48
  special = false
}

resource "aws_secretsmanager_secret" "callback" {
  name_prefix = "${local.name}-callback-"
  description = "Signs the pipeline's reports to the review app"
  kms_key_id  = aws_kms_key.data.arn
}

resource "aws_secretsmanager_secret_version" "callback" {
  secret_id     = aws_secretsmanager_secret.callback.id
  secret_string = random_password.callback.result
}

# What the review app itself may do on AWS: store uploads (which starts the pipeline), read them
# back for the page viewer, and start an execution to reprocess. Attach it to the app's role or user.
resource "aws_iam_policy" "review_app" {
  name        = "${local.name}-review-app"
  description = "The review app: uploads, page images and reprocessing"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "Uploads"
        Effect   = "Allow"
        Action   = ["s3:PutObject", "s3:GetObject"]
        Resource = "${aws_s3_bucket.documents.arn}/tenants/*"
      },
      {
        Sid      = "Reprocess"
        Effect   = "Allow"
        Action   = "states:StartExecution"
        Resource = aws_sfn_state_machine.pipeline.arn
      },
      {
        Sid      = "DataKey"
        Effect   = "Allow"
        Action   = ["kms:Decrypt", "kms:GenerateDataKey"]
        Resource = aws_kms_key.data.arn
      },
    ]
  })
}
