# RDS 복원용 일회성 이미지: postgres 클라이언트(psql) + 복원 스크립트 + 덤프.
# 앱 이미지(루트 Dockerfile)와 별개이고, ECS 태스크로 한 번 실행하고 끝난다.
# 빌드(deploy/ 폴더가 빌드 컨텍스트):  docker build --platform linux/amd64 --provenance=false -f deploy/restore.Dockerfile -t <ECR주소>:<태그> deploy
FROM postgres:17

COPY rds_restore.sh /rds_restore.sh
COPY pharma.sql.gz /pharma.sql.gz

USER postgres

# postgres 이미지의 기본 ENTRYPOINT는 DB 서버를 띄우므로 복원 스크립트로 덮어쓴다.
# 접속 정보(PGHOST 등)와 비밀번호는 이미지에 넣지 않고 태스크 정의가 환경변수로 준다.
ENTRYPOINT ["bash", "/rds_restore.sh"]
