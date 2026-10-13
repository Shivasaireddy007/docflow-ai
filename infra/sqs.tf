# Failed documents land here with their error, for inspection and redrive.
resource "aws_sqs_queue" "dead_letters" {
  name                              = "${local.name}-dead-letters"
  message_retention_seconds         = 1209600 # 14 days
  kms_master_key_id                 = aws_kms_key.data.id
  kms_data_key_reuse_period_seconds = 3600
}
