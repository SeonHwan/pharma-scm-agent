# apply가 끝나면 터미널에 출력되고, terraform output 으로 다시 볼 수 있음.

# SSM의 ro_dsn, ext_dsn에 적힌 호스트와 같은지 대조하는 데 사용(같은 식별자로 다시 만들면 같은 주소가 나오는지 확인).
output "rds_address" {
  value = aws_db_instance.main.address
}

# GitHub Actions의 변수(AWS_ROLE_ARN)에 넣을 값. 계정 ID가 들어 있어 워크플로 파일과 문서에는 적지 않음.
output "github_deploy_role_arn" {
  value = aws_iam_role.github_deploy.arn
}
