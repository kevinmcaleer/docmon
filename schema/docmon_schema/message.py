"""Build, split and parse docmon broadcast messages.

One "beat" from a node is a list of containers. It is sent as one or more
UDP datagrams; every datagram is a complete JSON object carrying the node
header plus a slice of the containers, along with ``seq``/``part``/``parts``
so a listener can tell when it has the whole beat.
"""

from __future__ import annotations

import json
import logging
from typing import Any

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1
DEFAULT_PORT = 50505
# Stays under a typical 1500-byte Ethernet MTU once IP/UDP headers are added,
# so a datagram is never fragmented.
DEFAULT_MAX_DATAGRAM = 1400

# Short key used in the message -> full OCI label name.
OCI_LABELS = {
    "source": "org.opencontainers.image.source",
    "revision": "org.opencontainers.image.revision",
    "created": "org.opencontainers.image.created",
    "version": "org.opencontainers.image.version",
}


def encode(message: dict[str, Any]) -> bytes:
    """Serialise a message compactly for the wire."""
    return json.dumps(message, separators=(",", ":"), ensure_ascii=False).encode()


def decode(data: bytes) -> dict[str, Any]:
    """Parse one datagram, rejecting anything that is not a docmon message."""
    message = json.loads(data)
    if not isinstance(message, dict) or "schema_version" not in message:
        raise ValueError("not a docmon message")
    if message["schema_version"] != SCHEMA_VERSION:
        raise ValueError(f"unsupported schema_version {message['schema_version']!r}")
    return message


def build_messages(
    *,
    node: dict[str, Any],
    containers: list[dict[str, Any]],
    sent_at: str,
    seq: int,
    interval: float,
    error: str | None = None,
    max_bytes: int = DEFAULT_MAX_DATAGRAM,
) -> list[dict[str, Any]]:
    """Split one beat into messages that each encode to at most ``max_bytes``.

    Containers are packed greedily in order. A single container that is too
    big on its own is still sent alone (it will be IP-fragmented, which is
    fine on a LAN) and a warning is logged. An empty container list still
    yields one message, so the beat doubles as a heartbeat.
    """
    header: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "node": node,
        "sent_at": sent_at,
        "interval": interval,
        "seq": seq,
    }
    if error:
        header["error"] = error

    def make(chunk: list[dict[str, Any]]) -> dict[str, Any]:
        # part/parts are placeholders here and filled in once the count is known.
        return {**header, "part": 0, "parts": 0, "containers": chunk}

    # Room for part/parts growing beyond a single digit.
    slack = 8
    chunks: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for container in containers:
        candidate = [*current, container]
        if current and len(encode(make(candidate))) + slack > max_bytes:
            chunks.append(current)
            current = [container]
        else:
            current = candidate
        if len(current) == 1 and len(encode(make(current))) + slack > max_bytes:
            log.warning(
                "container %s alone exceeds %d bytes; sending oversized datagram",
                container.get("name"),
                max_bytes,
            )
    chunks.append(current)

    parts = len(chunks)
    messages = []
    for index, chunk in enumerate(chunks, start=1):
        message = make(chunk)
        message["part"] = index
        message["parts"] = parts
        messages.append(message)
    return messages
