variable "project" {
  description = "Prefix for every resource name."
  type        = string
  default     = "docflow"
}

variable "environment" {
  type    = string
  default = "demo"
}

variable "region" {
  type    = string
  default = "ap-south-1"
}

variable "image_tag" {
  description = "Tag of the pipeline image in ECR (CI pushes the commit SHA)."
  type        = string
  default     = "bootstrap"
}

variable "model_api" {
  description = "\"openai\" for vLLM (or any OpenAI-compatible server), \"ollama\" for Ollama."
  type        = string
  default     = "openai"
  validation {
    condition     = contains(["openai", "ollama"], var.model_api)
    error_message = "model_api must be \"openai\" or \"ollama\"."
  }
}

variable "model_url" {
  description = "Base URL of the model server the OCR and extraction steps call."
  type        = string
}

variable "ocr_model" {
  type    = string
  default = "Qwen/Qwen2.5-VL-3B-Instruct"
}

variable "extraction_model" {
  type    = string
  default = "Qwen/Qwen2.5-7B-Instruct"
}

variable "model_concurrency" {
  description = "Most OCR or extraction calls in flight at once, so the model server isn't swamped."
  type        = number
  default     = 4
}

variable "model_retry_seconds" {
  description = "First wait before retrying a failed model call; doubles each time."
  type        = number
  default     = 10
}

variable "document_slo_ms" {
  description = "p95 time from upload to decision that the SLO alarm holds the pipeline to."
  type        = number
  default     = 30000
}

variable "alarm_email" {
  description = "Where alarms and budget warnings go; empty to skip the email subscription."
  type        = string
  default     = ""
}

variable "monthly_budget_usd" {
  type    = number
  default = 10
}

variable "github_repository" {
  description = "owner/name of the repository allowed to deploy through OIDC."
  type        = string
  default     = "Shivasaireddy007/docflow-ai"
}

variable "log_retention_days" {
  type    = number
  default = 30
}

variable "review_app_url" {
  description = "Base URL of the review app (e.g. https://review.example.com). Set it and the pipeline reports each result there and the app applies the rules; empty runs the pipeline standalone with rules from the bucket."
  type        = string
  default     = ""
}

variable "protect_data" {
  description = "Deletion protection on the results table. Set false (and apply) before `terraform destroy`."
  type        = bool
  default     = true
}
