# 앱 이미지(pharma-scm-agent)와 DB 복원용 이미지(restore-<커밋>)를 같이 보관하는 저장소.
resource "aws_ecr_repository" "app" {
  name = "pharma-scm-agent"

  # 같은 태그로 덮어쓰기를 막는다. 태그(git 짧은 해시)가 곧 커밋이라, 태그가 가리키는 이미지가 바뀌지 않는다.
  image_tag_mutability = "IMMUTABLE"

  # 이미지가 남아 있어도 terraform destroy가 저장소를 지운다. 기본값(false)이면 이미지가 있을 때 삭제가 실패한다.
  force_delete = true
}
