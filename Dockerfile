FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1

WORKDIR /app
RUN useradd --system --create-home --uid 10001 app

# 의존성 레이어(소스가 바뀌어도 캐시 유지)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
RUN uv sync --frozen --no-dev

USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).status == 200 else 1)"

# PHARMA_API_KEY, ANTHROPIC_API_KEY, PHARMA_*_DSN은 이미지에 넣지 않고 실행 시 환경변수로 준다.
CMD ["uv", "run", "--no-sync", "uvicorn", "pharma_scm.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
