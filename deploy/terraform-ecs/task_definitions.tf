locals {
  # SSM 파라미터의 ARN. 실행 역할(ssm-read-pharma)이 읽을 수 있는 /pharma/* 범위 안이다.
  ssm_arn_prefix = "arn:aws:ssm:${var.region}:${data.aws_caller_identity.current.account_id}:parameter/pharma"
}

# 앱 태스크 정의. 정의는 불변이라 값을 바꾸면 새 리비전이 만들어지고, 서비스가 그 리비전을 가리키게 된다.
resource "aws_ecs_task_definition" "app" {
  family = "pharma-scm-agent"

  # Fargate: 태스크마다 ENI와 IP를 받는 awsvpc 방식. cpu 1024 = 1 vCPU, memory는 MiB.
  # 규정 검색 모델(bge-m3)이 이미지에 들어 있어 메모리가 대기 약 0.8GB, 모델 파일 매핑까지 약 2GB다.
  # 0.5 vCPU는 검색 p95 약 0.7초, 1 vCPU는 약 0.35초였다(로컬 측정, docs/rag_eval_results.md §9).
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 1024
  memory                   = 3072

  # 이미지를 ECR에서 받고 SSM 비밀을 읽는 것은 실행 역할이 한다(앱 코드가 쓰는 태스크 역할은 두지 않는다).
  execution_role_arn = aws_iam_role.execution.arn

  # 로컬(Apple 실리콘)에서 빌드했을 때를 대비해 아키텍처를 명시한다. 이미지는 amd64로 올렸다.
  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([
    {
      name      = "api"
      image     = "${aws_ecr_repository.app.repository_url}:${var.app_image_tag}"
      essential = true

      portMappings = [{ containerPort = 8000, protocol = "tcp" }]

      # 값은 코드와 state에 없고, 태스크가 시작될 때 실행 역할이 SSM에서 읽어 환경변수로 넣는다.
      secrets = [
        { name = "PHARMA_API_KEY", valueFrom = "${local.ssm_arn_prefix}/api_key" },
        { name = "ANTHROPIC_API_KEY", valueFrom = "${local.ssm_arn_prefix}/anthropic_api_key" },
        { name = "PHARMA_RO_DSN", valueFrom = "${local.ssm_arn_prefix}/ro_dsn" },
        { name = "PHARMA_EXT_DSN", valueFrom = "${local.ssm_arn_prefix}/ext_dsn" },
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.api.name
          "awslogs-region"        = var.region
          "awslogs-stream-prefix" = "api"
        }
      }
    }
  ])
}

# DB 복원 태스크 정의. 서비스 없이 run-task로 한 번만 실행하는 일회성 작업이다.
resource "aws_ecs_task_definition" "restore" {
  family = "pharma-restore"

  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256
  memory                   = 1024

  execution_role_arn = aws_iam_role.execution.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([
    {
      name      = "restore"
      image     = "${aws_ecr_repository.app.repository_url}:${var.restore_image_tag}"
      essential = true

      # 접속 정보는 비밀이 아니므로 일반 환경변수로 둔다. 주소는 RDS 인스턴스에서 바로 가져온다.
      environment = [
        { name = "PGHOST", value = aws_db_instance.main.address },
        { name = "PGUSER", value = aws_db_instance.main.username },
        { name = "PGDATABASE", value = aws_db_instance.main.db_name },
      ]

      # 마스터 비밀번호와 앱용 두 역할의 비밀번호 3개는 SSM에서 주입한다.
      secrets = [
        { name = "PGPASSWORD", valueFrom = "${local.ssm_arn_prefix}/db_admin_password" },
        { name = "DB_RO_PASSWORD", valueFrom = "${local.ssm_arn_prefix}/db_ro_password" },
        { name = "DB_EXT_PASSWORD", valueFrom = "${local.ssm_arn_prefix}/db_ext_password" },
      ]

      # 같은 로그 그룹에 다른 접두사로 보낸다. 복원 결과(행 수)를 여기서 확인한다.
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.api.name
          "awslogs-region"        = var.region
          "awslogs-stream-prefix" = "restore"
        }
      }
    }
  ])
}
