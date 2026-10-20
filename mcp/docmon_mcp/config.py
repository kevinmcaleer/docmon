"""MCP server settings, read from DOCMON_* environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Config:
    # Base URL of the docmon listener's JSON API.
    listener_url: str = "http://127.0.0.1:8080"
    # "stdio" for a local client that starts the server, "http" for streamable HTTP.
    transport: str = "stdio"
    http_host: str = "0.0.0.0"
    http_port: int = 8081
    # Host headers the HTTP transport accepts (DNS rebinding protection), e.g.
    # "pi-1:*,192.168.1.10:*". Empty accepts any.
    allowed_hosts: tuple[str, ...] = ()
    # Look up OCI labels in the image's registry when the local image has none.
    registry_lookup: bool = True
    # Platform to read labels for when an image is multi-arch.
    platform: str = "linux/arm64"
    timeout: float = 10.0
    log_level: str = "INFO"

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> Config:
        env = os.environ if env is None else env
        get = env.get
        return cls(
            listener_url=get("DOCMON_LISTENER_URL", cls.listener_url).rstrip("/"),
            transport=get("DOCMON_MCP_TRANSPORT", cls.transport).lower(),
            http_host=get("DOCMON_MCP_HOST", cls.http_host),
            http_port=int(get("DOCMON_MCP_PORT", cls.http_port)),
            allowed_hosts=tuple(
                h.strip() for h in get("DOCMON_MCP_ALLOWED_HOSTS", "").split(",") if h.strip()
            ),
            registry_lookup=_bool(get("DOCMON_REGISTRY_LOOKUP", "true")),
            platform=get("DOCMON_PLATFORM", cls.platform),
            timeout=float(get("DOCMON_TIMEOUT", cls.timeout)),
            log_level=get("DOCMON_LOG_LEVEL", cls.log_level).upper(),
        )
