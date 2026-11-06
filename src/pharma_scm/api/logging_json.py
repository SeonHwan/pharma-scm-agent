"""JSON 한 줄 로그. 요청 ID는 contextvar로 들고 다녀 스레드 안에서도 같은 ID가 붙는다."""

import contextvars
import json
import logging
import sys
from datetime import datetime, timezone

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None)
_RESERVED = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def format(self, record):
        out = {"ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
               "level": record.levelname, "logger": record.name, "msg": record.getMessage(),
               "request_id": request_id_var.get()}
        out.update({k: v for k, v in record.__dict__.items() if k not in _RESERVED})
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        return json.dumps(out, ensure_ascii=False, default=str)


def setup_logging(level=logging.INFO):
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler._pharma_json = True
    log = logging.getLogger("pharma")
    # 이전 호출에서 붙인 우리 핸들러만 교체한다(다른 핸들러는 건드리지 않는다)
    log.handlers[:] = [h for h in log.handlers if not getattr(h, "_pharma_json", False)] + [handler]
    log.setLevel(level)
    log.propagate = False
    return log
