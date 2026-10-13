# The serverless processing path: an upload to S3 starts a Step Functions execution that runs
# the pipeline's steps as container Lambdas and records the decision in DynamoDB.
provider "aws" {
  region = var.region
  default_tags {
    tags = {
      Project     = var.project
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

locals {
  name       = "${var.project}-${var.environment}"
  account_id = data.aws_caller_identity.current.account_id
  partition  = data.aws_partition.current.partition
  steps = {
    prepare = { timeout = 60, memory = 1024, concurrency = null }
    ocr     = { timeout = 300, memory = 512, concurrency = var.model_concurrency }
    extract = { timeout = 120, memory = 512, concurrency = var.model_concurrency }
    decide  = { timeout = 60, memory = 512, concurrency = null }
  }
}
