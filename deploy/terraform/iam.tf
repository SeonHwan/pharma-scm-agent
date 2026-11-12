# 6단계: 서버가 자기 역할(IAM Role)로 SSM Parameter Store의 비밀을 직접 읽는다.
# 사용자 키를 서버에 두지 않는다. 역할은 /pharma/ 아래 파라미터의 읽기만 가능하다(최소 권한).
data "aws_caller_identity" "me" {}

resource "aws_iam_role" "p5" {
  name = "pharma-p5-ec2"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "p5_read_params" {
  name = "read-pharma-params"
  role = aws_iam_role.p5.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["ssm:GetParameter", "ssm:GetParameters"]
      Resource = "arn:aws:ssm:${var.region}:${data.aws_caller_identity.me.account_id}:parameter/pharma/*"
    }]
  })
}

# EC2에 역할을 붙이는 연결 장치
resource "aws_iam_instance_profile" "p5" {
  name = "pharma-p5-ec2"
  role = aws_iam_role.p5.name
}
