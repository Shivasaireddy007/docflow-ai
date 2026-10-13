# One customer-managed key for documents, results, queues and logs: access to data needs both
# the resource's permission and the key's, and every use of the key is in CloudTrail.
resource "aws_kms_key" "data" {
  description             = "${local.name} documents, results, queues and logs"
  enable_key_rotation     = true
  deletion_window_in_days = 7
  policy                  = data.aws_iam_policy_document.kms.json
}

resource "aws_kms_alias" "data" {
  name          = "alias/${local.name}"
  target_key_id = aws_kms_key.data.key_id
}

data "aws_iam_policy_document" "kms" {
  statement {
    sid       = "AccountAdministers"
    actions   = ["kms:*"]
    resources = ["*"]
    principals {
      type        = "AWS"
      identifiers = ["arn:${local.partition}:iam::${local.account_id}:root"]
    }
  }
  statement {
    sid       = "ServicesEncryptForUs"
    actions   = ["kms:Encrypt", "kms:Decrypt", "kms:ReEncrypt*", "kms:GenerateDataKey*", "kms:DescribeKey"]
    resources = ["*"]
    principals {
      type        = "Service"
      identifiers = ["logs.${var.region}.amazonaws.com", "sns.amazonaws.com", "events.amazonaws.com", "states.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
  }
}
