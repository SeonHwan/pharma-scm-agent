# 컨테이너가 출력한 로그가 모이는 곳. 태스크 정의의 awslogs 설정이 이 이름을 가리킨다.
# 미리 만들어 두면 실행 역할에 logs:CreateLogGroup 권한을 주지 않아도 된다.
resource "aws_cloudwatch_log_group" "api" {
  name = "/ecs/pharma-scm-agent"

  # 기본값은 무기한 보관이라 용량 과금이 계속 쌓인다. 학습용이라 7일만 둔다.
  retention_in_days = 7
}
