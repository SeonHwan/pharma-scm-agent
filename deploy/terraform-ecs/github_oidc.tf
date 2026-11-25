# GitHub Actions가 발급하는 신원 토큰을 AWS가 믿도록 등록한다. 계정(IAM)에 한 번만 등록하면 된다.
# 이 자원은 "GitHub이 발급한 토큰을 검증할 수 있다"는 것만 알려 준다. 어떤 저장소에 어떤 권한을 줄지는 아래의 역할이 정한다.
resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

# GitHub Actions 러너가 맡을 배포 역할. 신뢰 정책이 "누가 이 역할을 맡을 수 있는가"를 정한다.
# 맡은 뒤에 할 수 있는 일은 아래의 권한 정책(aws_iam_role_policy.github_deploy)이 정한다.
resource "aws_iam_role" "github_deploy" {
  name = "pharma-github-deploy"
  # IAM 역할 설명은 한글을 허용하지 않아(라틴 문자 범위만 가능) 영문으로 적는다.
  description = "Assumed by GitHub Actions on master to push images to ECR and deploy to ECS"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = aws_iam_openid_connect_provider.github.arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        # 토큰이 AWS STS용으로 발급된 경우만 허용한다.
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
          # 이 저장소의 master 브랜치에서 실행된 워크플로의 토큰만 허용한다(다른 저장소·브랜치·PR은 거부).
          # 저장소 표기는 숫자 ID가 붙은 불변 형식이다(variables.tf의 github_subject).
          "token.actions.githubusercontent.com:sub" = "repo:${var.github_subject}:ref:refs/heads/master"
        }
      }
    }]
  })
}

# 배포 역할이 할 수 있는 일. 필요한 동작만, 가능한 한 대상 자원을 좁혀서 허용한다(최소 권한).
resource "aws_iam_role_policy" "github_deploy" {
  name = "deploy-ecs"
  role = aws_iam_role.github_deploy.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      # 1) ECR 로그인 토큰. 이 동작은 특정 저장소로 범위를 좁힐 수 없어 모든 자원("*")에 허용한다.
      {
        Sid      = "EcrLogin"
        Effect   = "Allow"
        Action   = "ecr:GetAuthorizationToken"
        Resource = "*"
      },

      # 2) 이미지 push. 우리 저장소 하나에만 허용한다(받기 권한은 주지 않는다).
      {
        Sid    = "EcrPush"
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:InitiateLayerUpload",
          "ecr:UploadLayerPart",
          "ecr:CompleteLayerUpload",
          "ecr:PutImage",
        ]
        Resource = aws_ecr_repository.app.arn
      },

      # 3) 태스크 정의 조회와 새 리비전 등록. 이 두 동작은 자원 단위로 범위를 좁힐 수 없다("*").
      {
        Sid      = "EcsTaskDefinition"
        Effect   = "Allow"
        Action   = ["ecs:DescribeTaskDefinition", "ecs:RegisterTaskDefinition"]
        Resource = "*"
      },

      # 4) 서비스 갱신과 안정 대기용 조회. 서비스 pharma-api 하나에만 허용한다.
      # 서비스 자원을 참조하면 서비스가 없을 때 이 정책을 만들면서 서비스(과금)까지 만들게 되므로, ARN을 문자열로 조립한다.
      {
        Sid      = "EcsService"
        Effect   = "Allow"
        Action   = ["ecs:DescribeServices", "ecs:UpdateService"]
        Resource = "arn:aws:ecs:${var.region}:${data.aws_caller_identity.current.account_id}:service/${aws_ecs_cluster.main.name}/pharma-api"
      },

      # 5) 새 태스크 정의에 실행 역할을 지정하려면 그 역할을 ECS에 넘길 권한이 필요하다.
      # 대상은 실행 역할 하나로, 받는 쪽은 ECS 태스크로 제한한다(다른 역할을 붙여 권한을 키우는 것을 막음).
      {
        Sid       = "PassExecutionRole"
        Effect    = "Allow"
        Action    = "iam:PassRole"
        Resource  = aws_iam_role.execution.arn
        Condition = { StringEquals = { "iam:PassedToService" = "ecs-tasks.amazonaws.com" } }
      },
    ]
  })
}
