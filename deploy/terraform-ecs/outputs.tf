# apply가 끝나면 터미널에 출력되고, terraform output 으로 다시 볼 수 있다.

# SSM의 ro_dsn, ext_dsn에 적힌 호스트와 같은지 대조하는 데 쓴다(같은 식별자로 다시 만들면 같은 주소가 나오는지 확인).
output "rds_address" {
  value = aws_db_instance.main.address
}
