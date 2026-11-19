# 콘솔로 만든 실행 역할을 코드로 옮긴 것. 값은 iam get-role / get-role-policy 조회 결과(2026-11-19)와 같다.
# 실행 역할은 ECS가 컨테이너를 시작하기 전에 쓴다(ECR 이미지 받기, SSM 비밀 읽기, 로그 쓰기).
# 앱 코드가 AWS를 호출하지 않으므로 태스크 역할은 만들지 않는다.

data "aws_caller_identity" "current" {}

resource "aws_iam_role" "execution" {
  name        = "pharma-ecs-execution"
  description = "Allows ECS tasks to call AWS services on your behalf."

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = ""
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

# ECR 이미지 받기와 CloudWatch Logs 쓰기. AWS가 관리하는 정책이라 이름(ARN)만 붙인다.
resource "aws_iam_role_policy_attachment" "execution_managed" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# secrets에 적은 SSM SecureString을 시작할 때 읽는 권한. /pharma/* 로만 제한한다.
resource "aws_iam_role_policy" "ssm_read" {
  name = "ssm-read-pharma"
  role = aws_iam_role.execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid      = "Statement1"
      Effect   = "Allow"
      Action   = ["ssm:GetParameters"]
      Resource = ["arn:aws:ssm:${var.region}:${data.aws_caller_identity.current.account_id}:parameter/pharma/*"]
    }]
  })
}
