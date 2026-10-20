"""Agent settings, read from DOCMON_* environment variables."""

from __future__ import annotations

import os
import socket
from dataclasses import dataclass

from docmon_schema import DEFAULT_MAX_DATAGRAM, DEFAULT_PORT


def _bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Config:
    broadcast_addr: str = "255.255.255.255"
    port: int = DEFAULT_PORT
    interval: float = 60.0
    jitter: float = 5.0
    max_datagram: int = DEFAULT_MAX_DATAGRAM
    include_stopped: bool = False
    node_name: str | None = None
    node_ip: str | None = None
    log_level: str = "INFO"

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> Config:
        env = os.environ if env is None else env
        get = env.get
        return cls(
            broadcast_addr=get("DOCMON_BROADCAST_ADDR", cls.broadcast_addr),
            port=int(get("DOCMON_PORT", cls.port)),
            interval=float(get("DOCMON_INTERVAL", cls.interval)),
            jitter=float(get("DOCMON_JITTER", cls.jitter)),
            max_datagram=int(get("DOCMON_MAX_DATAGRAM", cls.max_datagram)),
            include_stopped=_bool(get("DOCMON_INCLUDE_STOPPED", "false")),
            node_name=get("DOCMON_NODE_NAME") or None,
            node_ip=get("DOCMON_NODE_IP") or None,
            log_level=get("DOCMON_LOG_LEVEL", cls.log_level).upper(),
        )


def node_name(config: Config) -> str:
    # With network_mode: host the container shares the host's UTS namespace,
    # so this is the Pi's own hostname.
    return config.node_name or socket.gethostname()


def node_ip(config: Config) -> str | None:
    """Best guess at this node's LAN address.

    Connecting a UDP socket sends nothing; it only asks the kernel which
    source address it would route from.
    """
    if config.node_ip:
        return config.node_ip
    for probe in ("10.255.255.255", "192.168.255.255", "8.8.8.8"):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.connect((probe, 1))
                address = sock.getsockname()[0]
        except OSError:
            continue
        if not address.startswith("127."):
            return address
    return None
