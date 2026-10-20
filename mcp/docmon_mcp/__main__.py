"""Entry point: ``docmon-mcp`` / ``python -m docmon_mcp``."""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import replace

from mcp.server.transport_security import TransportSecuritySettings

from docmon_mcp import __version__
from docmon_mcp.config import Config
from docmon_mcp.server import create_server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        help="stdio for a client that starts the server, http for streamable HTTP "
        "(default: DOCMON_MCP_TRANSPORT or stdio)",
    )
    parser.add_argument("--listener", help="listener URL (default: DOCMON_LISTENER_URL)")
    args = parser.parse_args(argv)

    config = Config.from_env()
    if args.transport:
        config = replace(config, transport=args.transport)
    if args.listener:
        config = replace(config, listener_url=args.listener.rstrip("/"))

    # stdout carries the protocol on stdio, so logs always go to stderr.
    logging.basicConfig(
        stream=sys.stderr,
        level=config.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if config.log_level != "DEBUG":
        # httpx logs every request at INFO.
        logging.getLogger("httpx").setLevel(logging.WARNING)
    log = logging.getLogger("docmon_mcp")
    server = create_server(config)

    if config.transport == "stdio":
        log.info("docmon-mcp %s on stdio, listener %s", __version__, config.listener_url)
        server.run("stdio")
    elif config.transport == "http":
        log.info(
            "docmon-mcp %s serving http://%s:%d/mcp, listener %s",
            __version__,
            config.http_host,
            config.http_port,
            config.listener_url,
        )
        security = None
        if config.allowed_hosts:
            security = TransportSecuritySettings(allowed_hosts=list(config.allowed_hosts))
        server.run(
            "streamable-http",
            host=config.http_host,
            port=config.http_port,
            transport_security=security,
        )
    else:
        parser.error(f"unknown transport {config.transport!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
