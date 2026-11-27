# RDS가 놓일 수 있는 서브넷 후보. 인스턴스는 단일 AZ여도 서로 다른 AZ의 서브넷이 2개 이상 필요.
# 서브넷은 ALB, ECS 서비스와 같은 목록(var.azs)을 사용.
resource "aws_db_subnet_group" "main" {
  name        = "pharma-db-subnets"
  description = "pharma-db subnets"
  subnet_ids  = data.aws_subnets.selected.ids
}

# DB 마스터 비밀번호. 코드에 값을 적지 않고 SSM의 SecureString을 읽어 옴.
# 복원 태스크도 같은 파라미터를 읽으므로 RDS와 복원 스크립트의 비밀번호가 항상 일치.
# 읽은 값은 terraform.tfstate에 평문으로 저장됨(.gitignore로 제외, 이 PC에만 둠).
data "aws_ssm_parameter" "db_admin_password" {
  name = "/pharma/db_admin_password"
}

# 앱이 읽는 DB. 시간 단위로 과금되는 자원이라 5단계 코드까지 쓴 뒤 다른 자원과 함께 apply.
resource "aws_db_instance" "main" {
  identifier = "pharma-db"

  engine         = "postgres"
  engine_version = "17"
  instance_class = "db.t4g.micro"

  # 20GiB 고정(자동 확장 끔). max_allocated_storage를 적지 않으면 늘어나지 않음.
  allocated_storage = 20
  storage_type      = "gp3"
  storage_encrypted = true

  # 마스터 계정과 첫 DB. db_name을 비우면 DB가 만들어지지 않음.
  db_name  = "pharma"
  username = "pharma_admin"
  password = data.aws_ssm_parameter.db_admin_password.value

  # 퍼블릭 IP 없이 pharma-rds-sg가 허용한 태스크 보안 그룹에서만 5432로 접속.
  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.rds.id]
  publicly_accessible    = false
  multi_az               = false

  backup_retention_period      = 1
  performance_insights_enabled = false

  # 철거 설정: 삭제 방지를 끄고, 최종 스냅샷과 자동 백업을 남기지 않음(남으면 용량 과금이 계속됨).
  deletion_protection      = false
  skip_final_snapshot      = true
  delete_automated_backups = true
}
