# var.azs에 적은 AZ의 기본 서브넷을 조회. RDS 서브넷 그룹, ALB, ECS 서비스가 모두 이 목록을 사용.
# 서로 다른 AZ를 고르면 ALB가 없는 AZ에 태스크가 놓여 타깃이 unused가 되므로, 한 곳에서 정해 같이 사용.
data "aws_subnets" "selected" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }

  filter {
    name   = "availability-zone"
    values = var.azs
  }
}
