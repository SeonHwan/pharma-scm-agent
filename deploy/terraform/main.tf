# aws_up.sh / aws_down.sh 와 같은 구성을 Terraform으로 선언한 것.
# 사용법은 deploy/terraform/README.md
terraform {
  required_version = ">= 1.5"
  required_providers {
    aws   = { source = "hashicorp/aws", version = "~> 5.0" }
    tls   = { source = "hashicorp/tls", version = "~> 4.0" }
    local = { source = "hashicorp/local", version = "~> 2.5" }
  }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = { Project = "pharma-p5" }
  }
}

# 6줄: create-key-pair. 개인키는 로컬에서 만들고 공개키만 AWS에 등록한다.
resource "tls_private_key" "p5" {
  algorithm = "ED25519"
}

resource "aws_key_pair" "p5" {
  key_name   = "pharma-p5"
  public_key = tls_private_key.p5.public_key_openssh
}

# 6~7줄: pem 저장과 chmod 600. server_up.sh가 이 경로를 그대로 쓴다.
resource "local_sensitive_file" "pem" {
  content         = tls_private_key.p5.private_key_openssh
  filename        = pathexpand("~/.ssh/pharma-p5.pem")
  file_permission = "0600"
}

# 8줄: 기본 VPC 조회
data "aws_vpc" "default" {
  default = true
}

# 12줄: 최신 AL2023 arm64 AMI (SSM 공개 파라미터)
data "aws_ssm_parameter" "ami" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64"
}

# 9~11줄: 보안 그룹. 22·8000을 허용 IP 하나에만 연다.
resource "aws_security_group" "p5" {
  name        = "pharma-p5"
  description = "pharma p5 temp"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "ssh"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.allowed_cidr]
  }
  ingress {
    description = "api"
    from_port   = 8000
    to_port     = 8000
    protocol    = "tcp"
    cidr_blocks = [var.allowed_cidr]
  }
  # CLI로 만든 SG는 아웃바운드 전체 허용이 기본이지만 Terraform은 명시하지 않으면 지운다.
  # 없으면 서버가 dnf·docker pull·Anthropic API를 호출하지 못한다.
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# run-instances
resource "aws_instance" "p5" {
  ami                    = data.aws_ssm_parameter.ami.value
  instance_type          = "t4g.small"
  key_name               = aws_key_pair.p5.key_name
  vpc_security_group_ids = [aws_security_group.p5.id]

  # 서버 안에서 shutdown 하면 중지가 아니라 삭제(user-data.sh가 3시간 뒤 종료를 예약한다)
  instance_initiated_shutdown_behavior = "terminate"

  user_data                   = file("${path.module}/../user-data.sh")
  user_data_replace_on_change = true

  root_block_device {
    volume_size           = 16
    volume_type           = "gp3"
    delete_on_termination = true
  }
  volume_tags = { Project = "pharma-p5" }

  # IMDSv2 강제(리뷰 사소한 항목)
  metadata_options {
    http_tokens = "required"
  }

  tags = { Name = "pharma-p5" }
}
