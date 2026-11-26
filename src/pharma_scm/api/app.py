"""FastAPI 서버: /ask(에이전트), /health(생존), /ready(준비).

- 요청 ID 미들웨어(X-Request-ID), JSON 로그, 단계별(LLM·도구) 소요 시간
- API 키 인증(X-API-Key), 키별 rate limit, 전체 타임아웃, 동시 실행 상한
- 오류는 {"error": {"code", "message", "request_id"}} 형식으로 통일
"""

import asyncio
import hashlib
import hmac
import logging
import os
import re
import time
import uuid
from contextlib import asynccontextmanager

import anthropic
import psycopg
from fastapi import Depends, FastAPI, Header
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from .. import config
from ..agent.graph import build_graph
from ..agent.observability import TimingCallback
from ..agent.prompt import PROMPT_VERSION
from ..agent.tools import sop_index
from ..agent.run import ask
from .logging_json import request_id_var, setup_logging
from .ratelimit import RateLimiter
from ..typedefs import AgentFn

_RID = re.compile(r"[A-Za-z0-9_-]{1,64}")
log = logging.getLogger("pharma.api")


class ApiError(Exception):
    def __init__(self, status, code, message, headers=None):
        self.status, self.code, self.message, self.headers = status, code, message, headers or {}


class AskRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    question: str = Field(min_length=1, max_length=1000)


def default_ready_checks():
    """외부 호출 없이 준비 상태만 본다(DB 연결, API 키 존재)."""
    config.load_env()
    checks = {}
    for name, dsn in (("db_readonly", config.RO_DSN), ("db_ext", config.EXT_DSN)):
        try:
            with psycopg.connect(dsn, connect_timeout=2) as conn:
                conn.execute("SELECT 1")
            checks[name] = "ok"
        except psycopg.Error as e:
            checks[name] = f"error:{type(e).__name__}"
    checks["anthropic_api_key"] = "ok" if os.environ.get("ANTHROPIC_API_KEY") else "error:missing"
    return checks


def make_real_agent():
    """진짜 에이전트를 만들어 호출 함수 fn(question, callbacks) -> ask() 결과 dict를 돌려준다.

    규정 검색 색인도 여기서 읽어 둔다. 색인이 없거나 문서와 맞지 않으면 첫 요청이 아니라 서버 시작에서 실패한다.
    """
    sop_index()
    graph = build_graph()
    return lambda q, cb: ask(q, graph, callbacks=cb)


class AgentRunner:
    """에이전트 호출 함수를 만드는 방법(factory)을 들고 있다가 처음 필요할 때 한 번만 만든다.

    호출 함수가 만들어지는 곳은 get() 안의 한 줄뿐이다.
    """

    def __init__(self, factory):
        self._factory = factory
        self._fn: AgentFn | None = None

    def get(self):
        if self._fn is None:
            self._fn = self._factory()
        return self._fn

    def run(self, question, callbacks):
        return self.get()(question, callbacks)


def create_app(settings, agent_factory=None, ready_checks=None):
    """agent_factory() -> fn(question, callbacks). 기본은 진짜 에이전트, 테스트는 가짜를 주입한다."""
    if not settings.api_keys:
        raise RuntimeError("PHARMA_API_KEY가 설정되지 않았다(인증 없이 서버를 띄우지 않는다)")
    setup_logging()
    limiter = RateLimiter(settings.rate_limit_per_min)
    sem = asyncio.Semaphore(settings.max_concurrency)
    agent = AgentRunner(agent_factory or make_real_agent)

    @asynccontextmanager
    async def lifespan(app):
        agent.get()  # 서버 시작 때 만들어 두면 모델 키가 없을 때 첫 요청이 아니라 시작에서 실패한다
        yield

    app = FastAPI(title="pharma-scm-agent", lifespan=lifespan)
    key_bytes = [k.encode() for k in settings.api_keys]

    @app.middleware("http")
    async def request_context(request, call_next):
        rid = request.headers.get("x-request-id", "")
        if not _RID.fullmatch(rid):
            rid = uuid.uuid4().hex
        token = request_id_var.set(rid)
        t0 = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["X-Request-ID"] = rid
            return response
        finally:
            log.info("request", extra={"method": request.method, "path": request.url.path,
                                       "status": status,
                                       "duration_ms": round((time.perf_counter() - t0) * 1000, 1)})
            request_id_var.reset(token)

    def _error(status, code, message, headers=None):
        return JSONResponse({"error": {"code": code, "message": message,
                                       "request_id": request_id_var.get()}},
                            status_code=status, headers=headers)

    @app.exception_handler(ApiError)
    async def _api_error(request, exc):
        return _error(exc.status, exc.code, exc.message, exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation(request, exc):
        fields = sorted({".".join(str(p) for p in e["loc"] if p != "body") for e in exc.errors()})
        return _error(422, "bad_request", f"요청 형식 오류: {', '.join(fields)}")

    @app.exception_handler(StarletteHTTPException)
    async def _http(request, exc):
        return _error(exc.status_code, "not_found" if exc.status_code == 404 else "http_error",
                      str(exc.detail))

    def require_key(x_api_key: str | None = Header(default=None)):
        given = (x_api_key or "").encode()
        if not any(hmac.compare_digest(given, k) for k in key_bytes) or not given:
            raise ApiError(401, "unauthorized", "API 키가 없거나 올바르지 않다")
        key_id = hashlib.sha256(given).hexdigest()[:8]
        ok, retry = limiter.check(key_id)
        if not ok:
            raise ApiError(429, "rate_limited", "요청이 너무 많다", {"Retry-After": str(retry)})
        return key_id

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/ready")
    def ready():
        checks = (ready_checks or default_ready_checks)()
        ok = all(v == "ok" for v in checks.values())
        return JSONResponse({"status": "ready" if ok else "not_ready", "checks": checks},
                            status_code=200 if ok else 503)

    @app.post("/ask")
    async def ask_endpoint(body: AskRequest, key_id=Depends(require_key)):
        cb = TimingCallback()
        t0 = time.perf_counter()

        async def run():
            async with sem:
                return await asyncio.to_thread(agent.run, body.question, [cb])

        try:
            result = await asyncio.wait_for(run(), settings.ask_timeout_s)
        except asyncio.TimeoutError:
            log.warning("ask_timeout", extra={"key_id": key_id, "stages": cb.stages})
            raise ApiError(504, "timeout", f"{settings.ask_timeout_s:g}초 안에 끝나지 않았다")
        except anthropic.RateLimitError:
            raise ApiError(503, "upstream_rate_limited", "모델 서비스가 요청을 제한하고 있다")
        except (anthropic.APIConnectionError, anthropic.APIStatusError) as e:
            log.error("upstream_error", extra={"error_type": type(e).__name__})
            raise ApiError(502, "upstream_error", "모델 서비스 호출에 실패했다")
        except Exception:
            log.exception("internal_error")
            raise ApiError(500, "internal_error", "내부 오류")
        latency_ms = round((time.perf_counter() - t0) * 1000, 1)
        info = {"key_id": key_id, "question_chars": len(body.question), "latency_ms": latency_ms,
                "tools_called": result["tools_called"], "tokens": result["tokens"],
                "stages": cb.stages, "error": result["error"]}
        if result["error"] == "loop_limit":
            log.warning("ask_loop_limit", extra=info)
            raise ApiError(508, "loop_limit", "도구 호출 횟수 상한에 걸려 답을 만들지 못했다")
        if not (result["answer"] or "").strip():
            log.warning("ask_empty_answer", extra=info)
            raise ApiError(502, "empty_answer", "모델이 빈 답을 돌려줬다")
        log.info("ask", extra={**info, "answer_chars": len(result["answer"])})
        return {"request_id": request_id_var.get(), "answer": result["answer"],
                "tools_called": result["tools_called"], "tokens": result["tokens"],
                "latency_ms": latency_ms, "stages": cb.stages, "prompt_version": PROMPT_VERSION}

    return app
