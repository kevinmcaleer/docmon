"""FastAPI app: JSON API and the web page."""

from __future__ import annotations

from contextlib import asynccontextmanager
from importlib import resources

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from docmon_listener import __version__, udp
from docmon_listener.config import Config
from docmon_listener.state import State


def create_app(config: Config, state: State, *, listen: bool = True) -> FastAPI:
    """Build the app. ``listen=False`` skips the UDP socket (for tests)."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        transport = await udp.start(state, config.bind, config.port) if listen else None
        try:
            yield
        finally:
            if transport is not None:
                transport.close()

    app = FastAPI(title="docmon", version=__version__, lifespan=lifespan)
    page = resources.files("docmon_listener").joinpath("static/index.html").read_text()

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def index() -> str:
        return page

    @app.get("/api/nodes")
    def nodes() -> list[dict]:
        return state.nodes()

    @app.delete("/api/nodes/{hostname}", status_code=204)
    def forget_node(hostname: str) -> None:
        if not state.forget(hostname):
            raise HTTPException(404, f"no node named {hostname!r}")

    @app.get("/api/containers")
    def containers(node: str | None = None, name: str | None = None, image: str | None = None):
        return state.containers(node=node, name=name, image=image)

    @app.get("/api/containers/{name}")
    def container(name: str) -> list[dict]:
        """Every container with exactly this name; the same name can run on several nodes."""
        matches = [c for c in state.containers(name=name) if c.get("name") == name]
        if not matches:
            raise HTTPException(404, f"no container named {name!r}")
        return matches

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict:
        return {"ok": True}

    return app
