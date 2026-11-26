variable "region" {
  type    = string
  default = "ap-northeast-2"
}

# ALB와 서비스가 같은 서브넷을 쓰게 하는 변수. 서로 다른 AZ를 고르면 타깃이 unused가 된다(2d 사례).
variable "azs" {
  type        = list(string)
  default     = ["ap-northeast-2c", "ap-northeast-2d"]
  description = "ALB와 서비스가 함께 쓸 AZ"
}

# 접속 대상에 따라 출발 IP가 달라지는 네트워크가 있어(이 PC는 3가지로 보였다) 목록으로 받는다.
variable "allowed_cidrs" {
  type        = list(string)
  description = "ALB 80을 허용할 IP 목록. 예: [\"1.2.3.4/32\"]"

  validation {
    condition     = length(var.allowed_cidrs) > 0 && alltrue([for c in var.allowed_cidrs : can(cidrhost(c, 0)) && c != "0.0.0.0/0"])
    error_message = "비어 있지 않아야 하고, 모두 올바른 CIDR이어야 하며, 전 세계 개방(0.0.0.0/0)은 허용하지 않는다."
  }
}

# 서비스가 띄울 앱 이미지의 태그. ECR에 올린 태그(git 짧은 해시)를 적는다. 불변 태그라 같은 태그를 덮어쓸 수 없다.
variable "app_image_tag" {
  type        = string
  default     = "ea13c2a"
  description = "앱 이미지 태그"
}

variable "restore_image_tag" {
  type        = string
  default     = "restore-ea13c2a"
  description = "DB 복원 이미지 태그"
}

# 서비스가 유지할 태스크 수. 비용 때문에 1로 둔다(가용성과 처리량은 N개일 때 얻는다).
variable "desired_count" {
  type        = number
  default     = 1
  description = "서비스가 유지할 앱 태스크 수"
}

# 배포 역할을 맡을 수 있는 GitHub 저장소를 토큰의 sub 값에서 가리키는 부분("repo:" 뒤, ":ref:..." 앞).
# 이 저장소는 sub에 소유자·저장소의 숫자 ID가 붙는 형식(불변 형식)을 쓴다. 이름만 쓰면 일치하지 않아 역할을 맡을 수 없다.
# 값은 `gh api repos/소유자/저장소/actions/oidc/customization/sub`의 sub_claim_prefix에서 "repo:" 뒤를 가져온다.
variable "github_subject" {
  type        = string
  default     = "SeonHwan@60860713/pharma-scm-agent@1473726648"
  description = "배포 역할을 맡을 수 있는 GitHub 저장소의 sub 표기(불변 형식)"
}
