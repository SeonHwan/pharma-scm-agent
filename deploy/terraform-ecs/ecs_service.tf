# 앱 태스크를 desired_count개로 유지하는 서비스. 죽거나 멈춘 태스크는 새로 띄우고,
# 새 태스크의 IP는 타깃 그룹에 등록하고 내려가는 태스크의 IP는 해제한다.
resource "aws_ecs_service" "api" {
  name            = "pharma-api"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.app.arn
  desired_count   = var.desired_count
  launch_type     = "FARGATE"

  # 새 태스크가 뜬 직후 헬스 체크가 실패해도 60초 동안은 교체하지 않는다(앱이 시작하는 시간).
  health_check_grace_period_seconds = 60

  # 롤링 배포가 계속 실패하면 배포를 멈추고 직전 리비전으로 되돌린다. 실제 롤백은 아직 검증하지 않았다.
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  # 태스크가 놓일 서브넷은 ALB와 같은 목록이다. NAT가 없으므로 퍼블릭 IP로 ECR과 SSM에 나간다.
  network_configuration {
    subnets          = data.aws_subnets.selected.ids
    security_groups  = [aws_security_group.task.id]
    assign_public_ip = true
  }

  # 서비스에는 타깃 그룹 ARN, 컨테이너 이름, 컨테이너 포트만 저장된다. 이름은 태스크 정의와 같아야 한다.
  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = 8000
  }

  # 타깃 그룹이 리스너에 연결된 뒤에야 서비스를 만들 수 있다(ARN을 참조하지 않아 순서를 직접 적는다).
  depends_on = [aws_lb_listener.http]
}
