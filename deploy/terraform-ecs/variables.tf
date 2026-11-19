variable "region" {
  type    = string
  default = "ap-northeast-2"
}

# ALB와 서비스가 같은 서브넷을 쓰게 하는 변수. 서로 다른 AZ를 고르면 타깃이 unused가 된다(2d 사례).
variable "azs" {
  type        = list(string)
  default     = ["ap-northeast-2a", "ap-northeast-2b"]
  description = "ALB와 서비스가 함께 쓸 AZ"
}

variable "allowed_cidr" {
  type        = string
  description = "ALB 80을 허용할 IP. 예: 1.2.3.4/32"

  validation {
    condition     = can(cidrhost(var.allowed_cidr, 0)) && var.allowed_cidr != "0.0.0.0/0"
    error_message = "올바른 CIDR이어야 하고, 전 세계 개방(0.0.0.0/0)은 허용하지 않는다."
  }
}
