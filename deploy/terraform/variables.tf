variable "region" {
  type    = string
  default = "ap-northeast-2"
}

variable "allowed_cidr" {
  type        = string
  description = "22·8000을 허용할 IP. 예: 1.2.3.4/32 (curl checkip.amazonaws.com 결과 뒤에 /32)"

  validation {
    condition     = can(cidrhost(var.allowed_cidr, 0)) && var.allowed_cidr != "0.0.0.0/0"
    error_message = "올바른 CIDR이어야 하고, 전 세계 개방(0.0.0.0/0)은 허용하지 않는다."
  }
}
