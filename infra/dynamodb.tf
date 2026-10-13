# One item per document, keyed "<tenant>#<sha256>". by_tenant lists a tenant's documents by
# upload time; by_status is the review queue ("needs_review", oldest first).
resource "aws_dynamodb_table" "results" {
  name         = "${local.name}-results"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"

  attribute {
    name = "pk"
    type = "S"
  }
  attribute {
    name = "tenant_id"
    type = "S"
  }
  attribute {
    name = "status"
    type = "S"
  }
  attribute {
    name = "uploaded_at"
    type = "S"
  }

  global_secondary_index {
    name = "by_tenant"
    key_schema {
      attribute_name = "tenant_id"
      key_type       = "HASH"
    }
    key_schema {
      attribute_name = "uploaded_at"
      key_type       = "RANGE"
    }
    projection_type = "ALL"
  }

  global_secondary_index {
    name = "by_status"
    key_schema {
      attribute_name = "status"
      key_type       = "HASH"
    }
    key_schema {
      attribute_name = "uploaded_at"
      key_type       = "RANGE"
    }
    projection_type    = "INCLUDE"
    non_key_attributes = ["tenant_id", "confidence", "filename"]
  }

  point_in_time_recovery {
    enabled = true
  }
  server_side_encryption {
    enabled     = true
    kms_key_arn = aws_kms_key.data.arn
  }
  deletion_protection_enabled = var.protect_data
}

# Model results by content and step version (the same design as Redis locally); TTL expires them.
resource "aws_dynamodb_table" "cache" {
  name         = "${local.name}-cache"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "key"

  attribute {
    name = "key"
    type = "S"
  }
  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }
  server_side_encryption {
    enabled     = true
    kms_key_arn = aws_kms_key.data.arn
  }
}
