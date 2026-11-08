output "public_ip" {
  value = aws_instance.p5.public_ip
}

output "instance_id" {
  value = aws_instance.p5.id
}

output "next" {
  value = "deploy/server_up.sh ${aws_instance.p5.public_ip}   (저장소 루트에서, 3시간 뒤 자동 종료)"
}
