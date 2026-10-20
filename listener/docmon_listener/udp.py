"""Receive agent datagrams and feed them into the state."""

from __future__ import annotations

import asyncio
import logging
import socket

from docmon_schema import decode

from docmon_listener.state import State

log = logging.getLogger(__name__)


class BeatProtocol(asyncio.DatagramProtocol):
    def __init__(self, state: State) -> None:
        self.state = state

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        try:
            message = decode(data)
            if self.state.accept(message, addr[0]):
                log.debug("beat from %s (%s)", message["node"]["hostname"], addr[0])
        except (ValueError, KeyError, TypeError) as exc:
            log.debug("ignoring datagram from %s: %s", addr[0], exc)


def open_socket(bind: str, port: int) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    # Lets a second listener (or `nc -ul`) share the port while debugging.
    if hasattr(socket, "SO_REUSEPORT"):
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    sock.bind((bind, port))
    return sock


async def start(state: State, bind: str, port: int) -> asyncio.DatagramTransport:
    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(
        lambda: BeatProtocol(state), sock=open_socket(bind, port)
    )
    log.info("listening for beats on udp://%s:%d", bind, port)
    return transport
