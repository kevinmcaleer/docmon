"""Listener settings, read from DOCMON_* environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass

from docmon_schema import DEFAULT_PORT


@dataclass(frozen=True)
class Config:
    bind: str = "0.0.0.0"
    port: int = DEFAULT_PORT
    http_host: str = "0.0.0.0"
    http_port: int = 8080
    # A node is stale after this many intervals without a datagram.
    stale_after: float = 3.0
    # ...and gone after this many seconds. 0 never marks nodes gone.
    gone_after: float = 3600.0
    # SQLite file to keep state across restarts. Empty keeps state in memory only.
    db: str = ""
    log_level: str = "INFO"

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> Config:
        env = os.environ if env is None else env
        get = env.get
        return cls(
            bind=get("DOCMON_BIND", cls.bind),
            port=int(get("DOCMON_PORT", cls.port)),
            http_host=get("DOCMON_HTTP_HOST", cls.http_host),
            http_port=int(get("DOCMON_HTTP_PORT", cls.http_port)),
            stale_after=float(get("DOCMON_STALE_AFTER", cls.stale_after)),
            gone_after=float(get("DOCMON_GONE_AFTER", cls.gone_after)),
            db=get("DOCMON_DB", cls.db),
            log_level=get("DOCMON_LOG_LEVEL", cls.log_level).upper(),
        )
