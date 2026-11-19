# 콘솔로 만든 보안 그룹 3개를 코드로 옮긴 것. 값은 describe-security-groups 조회 결과(2026-11-19)와 같다.
# 이름·설명·VPC를 바꾸면 보안 그룹이 지워지고 다시 만들어지므로 조회한 값 그대로 둔다.

data "aws_vpc" "default" {
  default = true
}

# ALB: 허용한 IP에서 오는 80만 받는다.
resource "aws_security_group" "alb" {
  name        = "pharma-alb-sg"
  description = "Allow HTTP 80 from my IP to the ALB"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = [var.allowed_cidr]
  }

  # Terraform은 명시하지 않은 아웃바운드를 지운다. 콘솔이 기본으로 만든 전체 허용을 그대로 적는다.
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# 태스크: ALB 보안 그룹에서 오는 8000만 받는다(IP가 아니라 보안 그룹을 출처로 지정).
resource "aws_security_group" "task" {
  name        = "pharma-task-sg"
  description = "Allow 8000 from the ALB to ECS tasks"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# RDS: 태스크 보안 그룹에서 오는 5432만 받는다.
resource "aws_security_group" "rds" {
  name        = "pharma-rds-sg"
  description = "Allow Postgres 5432 from ECS tasks to RDS"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.task.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}
