# 서비스와 태스크를 담는 논리적 묶음. 클러스터 자체는 서버가 아니고 켜 둔다고 과금되지도 않음.
# Fargate를 쓰므로 서버(EC2)를 등록할 일이 없음. 서비스를 만들 때 launch_type = "FARGATE"로 지정.
resource "aws_ecs_cluster" "main" {
  name = "pharma-cluster"
}
