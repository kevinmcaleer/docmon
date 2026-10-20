"""Reassemble beats from datagrams and keep the latest report per node."""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

log = logging.getLogger(__name__)

# Unfinished beats are dropped after this many seconds.
PENDING_TIMEOUT = 30.0


@dataclass
class NodeReport:
    hostname: str
    ip: str | None
    agent: str | None
    interval: float
    seq: int
    sent_at: str | None
    error: str | None
    containers: list[dict[str, Any]]
    # Wall-clock seconds of the last datagram from this node, and of the last
    # complete beat. A node whose beats keep losing a part still counts as alive.
    last_seen: float
    last_beat: float
    addr: str | None = None


@dataclass
class _Pending:
    header: dict[str, Any]
    parts: int
    started: float
    received: dict[int, list[dict[str, Any]]] = field(default_factory=dict)


def _validate(message: dict[str, Any]) -> tuple[str, int, int, int]:
    node = message.get("node")
    hostname = node.get("hostname") if isinstance(node, dict) else None
    seq, part, parts = message.get("seq"), message.get("part"), message.get("parts")
    if not isinstance(hostname, str) or not hostname:
        raise ValueError("missing node.hostname")
    if not all(isinstance(v, int) for v in (seq, part, parts)) or not 1 <= part <= parts:
        raise ValueError("bad seq/part/parts")
    if not isinstance(message.get("containers"), list):
        raise ValueError("containers is not a list")
    return hostname, seq, part, parts


def parse_started_at(value: str | None) -> datetime | None:
    """Parse Docker's StartedAt, which has nanoseconds that Python can't take."""
    if not value or value.startswith("0001-"):
        return None
    text = value.replace("Z", "+00:00")
    if "." in text:
        head, _, rest = text.partition(".")
        digits = "".join(c for c in rest if c.isdigit())
        text = f"{head}.{digits[:6]}{rest[len(digits) :]}"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


class State:
    """Thread-safe store of node reports. ``clock`` returns wall-clock seconds."""

    def __init__(
        self,
        *,
        stale_after: float = 3.0,
        gone_after: float = 3600.0,
        db: str = "",
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.stale_after = stale_after
        self.gone_after = gone_after
        self.clock = clock
        self._lock = threading.Lock()
        self._nodes: dict[str, NodeReport] = {}
        self._pending: dict[tuple[str, int], _Pending] = {}
        self._db = self._open_db(db) if db else None

    # -- persistence ---------------------------------------------------------

    def _open_db(self, path: str) -> sqlite3.Connection:
        conn = sqlite3.connect(path, check_same_thread=False)
        conn.execute("CREATE TABLE IF NOT EXISTS nodes (hostname TEXT PRIMARY KEY, report TEXT)")
        for (report,) in conn.execute("SELECT report FROM nodes"):
            try:
                node = NodeReport(**json.loads(report))
            except (TypeError, ValueError) as exc:
                log.warning("skipping unreadable saved node: %s", exc)
                continue
            self._nodes[node.hostname] = node
        log.info("loaded %d node(s) from %s", len(self._nodes), path)
        return conn

    def _save(self, node: NodeReport) -> None:
        if self._db is not None:
            with self._db:
                self._db.execute(
                    "INSERT OR REPLACE INTO nodes VALUES (?, ?)",
                    (node.hostname, json.dumps(asdict(node))),
                )

    # -- ingest --------------------------------------------------------------

    def accept(self, message: dict[str, Any], addr: str | None = None) -> bool:
        """Take one decoded datagram. Returns True when it completed a beat."""
        hostname, seq, part, parts = _validate(message)
        now = self.clock()
        with self._lock:
            self._expire_pending(now)
            node = self._nodes.get(hostname)
            if node is not None:
                node.last_seen = now
                node.addr = addr or node.addr

            key = (hostname, seq)
            pending = self._pending.get(key)
            if pending is None or pending.parts != parts:
                pending = self._pending[key] = _Pending(header=message, parts=parts, started=now)
            pending.received[part] = message["containers"]
            if len(pending.received) < parts:
                return False
            del self._pending[key]

            containers = [c for i in range(1, parts + 1) for c in pending.received[i]]
            header = pending.header
            node_info = header["node"]
            node = NodeReport(
                hostname=hostname,
                ip=node_info.get("ip"),
                agent=node_info.get("agent"),
                interval=float(header.get("interval") or 60.0),
                seq=seq,
                sent_at=header.get("sent_at"),
                error=header.get("error"),
                containers=sorted(containers, key=lambda c: str(c.get("name", ""))),
                last_seen=now,
                last_beat=now,
                addr=addr,
            )
            self._nodes[hostname] = node
            self._save(node)
            return True

    def _expire_pending(self, now: float) -> None:
        for key in [k for k, p in self._pending.items() if now - p.started > PENDING_TIMEOUT]:
            log.debug("dropping incomplete beat %s", key)
            del self._pending[key]

    def forget(self, hostname: str) -> bool:
        with self._lock:
            found = self._nodes.pop(hostname, None) is not None
            if found and self._db is not None:
                with self._db:
                    self._db.execute("DELETE FROM nodes WHERE hostname = ?", (hostname,))
            return found

    # -- queries -------------------------------------------------------------

    def status(self, node: NodeReport, now: float) -> str:
        age = now - node.last_seen
        if self.gone_after and age > self.gone_after:
            return "gone"
        if age > self.stale_after * node.interval:
            return "stale"
        return "online"

    def nodes(self) -> list[dict[str, Any]]:
        now = self.clock()
        with self._lock:
            nodes = sorted(self._nodes.values(), key=lambda n: n.hostname)
            return [self._node_view(n, now) for n in nodes]

    def _node_view(self, node: NodeReport, now: float) -> dict[str, Any]:
        return {
            "hostname": node.hostname,
            "ip": node.ip or node.addr,
            "agent": node.agent,
            "status": self.status(node, now),
            "error": node.error,
            "interval": node.interval,
            "last_seen": _iso(node.last_seen),
            "last_seen_seconds_ago": round(now - node.last_seen, 1),
            "container_count": len(node.containers),
        }

    def containers(
        self, *, node: str | None = None, name: str | None = None, image: str | None = None
    ) -> list[dict[str, Any]]:
        """All containers across nodes. ``name`` and ``image`` match substrings."""
        now = self.clock()
        result = []
        with self._lock:
            for report in sorted(self._nodes.values(), key=lambda n: n.hostname):
                if node and report.hostname != node:
                    continue
                status = self.status(report, now)
                for container in report.containers:
                    if name and name.lower() not in str(container.get("name", "")).lower():
                        continue
                    if image and image.lower() not in str(container.get("image", "")).lower():
                        continue
                    result.append(_container_view(container, report, status, now))
        return result


def _iso(seconds: float) -> str:
    return datetime.fromtimestamp(seconds, UTC).isoformat(timespec="seconds")


def _container_view(
    container: dict[str, Any], node: NodeReport, node_status: str, now: float
) -> dict[str, Any]:
    started = parse_started_at(container.get("started_at"))
    uptime = None
    if started is not None and container.get("status") == "running":
        uptime = max(0, int(now - started.timestamp()))
    return {
        **container,
        "node": node.hostname,
        "node_status": node_status,
        "uptime_seconds": uptime,
    }
