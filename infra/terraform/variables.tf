variable "project" {
  description = "Project name used as prefix for all resources"
  type        = string
  default     = "resolute"
}

variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

variable "database_url" {
  description = "PostgreSQL connection string (Supabase or RDS)"
  type        = string
  sensitive   = true
}

variable "redis_url" {
  description = "Redis connection string (Upstash or ElastiCache)"
  type        = string
  sensitive   = true
}
