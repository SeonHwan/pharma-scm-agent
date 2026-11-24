# ALB가 요청을 보낼 태스크들의 명단과 헬스 체크 설정. 태스크의 IP는 ECS 서비스가 등록하고 해제하므로
# 여기에는 대상(target)을 적지 않는다.
resource "aws_lb_target_group" "api" {
  name     = "pharma-tg"
  port     = 8000
  protocol = "HTTP"
  vpc_id   = data.aws_vpc.default.id

  # Fargate 태스크는 서버가 아니라 태스크마다 ENI와 IP를 받으므로 IP 방식이다.
  target_type = "ip"

  # 기본값(300초)은 배포와 철거를 느리게 한다. 처리 중인 요청을 마칠 시간으로 30초만 준다.
  deregistration_delay = 30

  # 기본값에 맡기지 않고 명시한다. /health는 프로세스 생존만 본다(/ready로 하면 DB 장애 때 태스크가 계속 교체됨).
  health_check {
    path                = "/health"
    matcher             = "200"
    interval            = 15
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 2
  }
}

# 외부에서 들어오는 단일 진입점. 시간 단위로 과금되는 자원이다.
# subnets에 적은 서브넷마다(AZ마다) ALB 노드가 하나씩 생기고, 이 목록은 서비스가 쓰는 목록과 같다.
resource "aws_lb" "main" {
  name               = "pharma-alb"
  load_balancer_type = "application"
  internal           = false

  # 80 포트는 pharma-alb-sg가 var.allowed_cidrs에서 오는 요청만 허용한다.
  security_groups = [aws_security_group.alb.id]
  subnets         = data.aws_subnets.selected.ids
}

# ALB가 80 포트로 받은 요청을 타깃 그룹으로 넘기는 규칙. HTTPS(443)는 쓰지 않는다.
resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }
}
