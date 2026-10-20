"""Entry point: ``docmon-agent`` / ``python -m docmon_agent``."""

from __future__ import annotations

import argparse
import json
import logging
import random
import signal
import socket
import threading
from datetime import UTC, datetime

from docmon_schema import build_messages, encode

from docmon_agent import __version__
from docmon_agent.collect import collect_containers
from docmon_agent.config import Config, node_ip, node_name

log = logging.getLogger("docmon_agent")


def beat(client, config: Config, seq: int) -> list[dict]:
    """Collect this node's containers and build the datagrams for one beat."""
    error = None
    try:
        containers = collect_containers(client, include_stopped=config.include_stopped)
    except Exception as exc:  # noqa: BLE001 - keep beating even if Docker is down
        log.warning("could not read containers: %s", exc)
        containers, error = [], f"docker: {exc}"
    return build_messages(
        node={"hostname": node_name(config), "ip": node_ip(config), "agent": __version__},
        containers=containers,
        sent_at=datetime.now(UTC).isoformat(timespec="seconds"),
        seq=seq,
        interval=config.interval,
        error=error,
        max_bytes=config.max_datagram,
    )


def send(sock: socket.socket, config: Config, messages: list[dict]) -> None:
    for message in messages:
        sock.sendto(encode(message), (config.broadcast_addr, config.port))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="send a single beat and exit")
    parser.add_argument(
        "--dry-run", action="store_true", help="print the datagrams instead of sending them"
    )
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args(argv)

    config = Config.from_env()
    logging.basicConfig(
        level=config.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    import docker

    client = docker.from_env()
    stop = threading.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_: stop.set())

    log.info(
        "docmon-agent %s on %s broadcasting to %s:%d every %ss",
        __version__,
        node_name(config),
        config.broadcast_addr,
        config.port,
        config.interval,
    )
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        seq = 0
        while not stop.is_set():
            messages = beat(client, config, seq)
            if args.dry_run:
                for message in messages:
                    print(json.dumps(message, indent=2))
            else:
                try:
                    send(sock, config, messages)
                except OSError as exc:
                    log.warning("send failed: %s", exc)
                else:
                    log.debug("beat %d: %d datagram(s)", seq, len(messages))
            if args.once:
                break
            seq += 1
            # Jitter keeps a rack of Pis that booted together from beating in lockstep.
            stop.wait(config.interval + random.uniform(0, config.jitter))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
