# 7단계 ECS Fargate 구성을 Terraform으로 선언. 콘솔로 만든 것과 같은 구성이 목표.
# state는 로컬 파일(혼자 사용). 비밀번호가 들어갈 수 있어 .gitignore에 포함.
terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = { Project = "pharma-ecs" }
  }
}
