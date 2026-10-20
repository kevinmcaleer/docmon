"""Entry point: ``docmon-listener`` / ``python -m docmon_listener``."""

from __future__ import annotations

import argparse
import logging

import uvicorn

from docmon_listener import __version__
from docmon_listener.app import create_app
from docmon_listener.config import Config
from docmon_listener.state import State


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    parser.parse_args(argv)

    config = Config.from_env()
    logging.basicConfig(
        level=config.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    state = State(stale_after=config.stale_after, gone_after=config.gone_after, db=config.db)
    logging.getLogger("docmon_listener").info(
        "docmon-listener %s serving http://%s:%d", __version__, config.http_host, config.http_port
    )
    uvicorn.run(
        create_app(config, state),
        host=config.http_host,
        port=config.http_port,
        log_level="warning" if config.log_level == "INFO" else config.log_level.lower(),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
