import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    api_keys: tuple[str, ...]
    ask_timeout_s: float = 60.0
    rate_limit_per_min: int = 30
    max_concurrency: int = 8

    @classmethod
    def from_env(cls):
        keys = tuple(k.strip() for k in os.environ.get("PHARMA_API_KEY", "").split(",") if k.strip())
        return cls(api_keys=keys,
                   ask_timeout_s=float(os.environ.get("PHARMA_ASK_TIMEOUT_S", 60)),
                   rate_limit_per_min=int(os.environ.get("PHARMA_RATE_LIMIT_PER_MIN", 30)),
                   max_concurrency=int(os.environ.get("PHARMA_MAX_CONCURRENCY", 8)))
