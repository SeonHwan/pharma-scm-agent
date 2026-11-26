FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /usr/local/bin/uv
# HF_HOME: 임베딩 모델을 이미지 안의 고정 위치에 둔다(실행 사용자와 무관하게 읽을 수 있게).
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1 HF_HOME=/opt/hf

WORKDIR /app
RUN useradd --system --create-home --uid 10001 app

# 의존성 레이어(소스가 바뀌어도 캐시 유지). PyTorch는 CPU 빌드다(pyproject.toml의 pytorch-cpu 저장소).
# uv 다운로드 캐시는 빌드 캐시 마운트에 두어 이미지에 남기지 않는다(남기면 약 1.2GB가 더 든다).
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-install-project

# 임베딩 모델 레이어(bge-m3, 고정 리비전, 필요한 파일만 약 2.3GB). 이 파일 하나만 복사해서 실행하므로
# 다른 소스가 바뀌어도 이 레이어는 캐시된다.
COPY src/pharma_scm/retrieval/models.py /tmp/models.py
# 내려받은 캐시 파일 일부가 root 전용(600)이라, 실행 사용자(app)도 읽을 수 있게 권한을 연다.
RUN uv run --no-sync python /tmp/models.py && rm /tmp/models.py && chmod -R a+rX /opt/hf

COPY src ./src
COPY sop ./sop
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev
# 규정 검색 색인(섹션 벡터)을 빌드 때 만든다. 서버는 시작할 때 읽기만 하고, 문서와 맞지 않으면 시작하지 않는다.
RUN uv run --no-sync python -m pharma_scm.retrieval.index

# 실행 중에는 모델 저장소에 접속하지 않는다(모델은 이미지에 있다).
ENV HF_HUB_OFFLINE=1
# PyTorch는 컨테이너 밖 호스트의 코어 수(예: 16)만큼 스레드를 띄우는데, CPU 할당량이 0.5~1 vCPU면 스레드들이
# 할당량을 순식간에 다 쓰고 멈춰서 질의 하나가 4.5초까지 걸렸다(docs/rag_eval_results.md §9). 1개로 고정한다.
ENV OMP_NUM_THREADS=1
USER app
EXPOSE 8000
# 시작 때 모델과 색인을 읽으므로 start-period를 넉넉히 둔다.
HEALTHCHECK --interval=30s --timeout=3s --start-period=60s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).status == 200 else 1)"

# PHARMA_API_KEY, ANTHROPIC_API_KEY, PHARMA_*_DSN은 이미지에 넣지 않고 실행 시 환경변수로 준다.
CMD ["uv", "run", "--no-sync", "uvicorn", "pharma_scm.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
