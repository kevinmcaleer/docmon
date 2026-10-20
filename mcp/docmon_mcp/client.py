"""Thin async client for the listener's JSON API."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx
from mcp.server.mcpserver.exceptions import ToolError


class ListenerError(ToolError):
    """The listener could not be reached or answered with an error.

    A ToolError, so the client sees the message rather than a generic failure.
    """


class ListenerClient:
    def __init__(self, base_url: str, *, timeout: float = 10.0, client=None) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = client or httpx.AsyncClient(timeout=timeout)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _get(self, path: str, params: dict[str, str] | None = None) -> Any:
        url = self.base_url + path
        try:
            response = await self._client.get(url, params=params)
        except httpx.HTTPError as exc:
            raise ListenerError(
                f"cannot reach the docmon listener at {self.base_url}: {exc}"
            ) from exc
        if response.status_code == 404:
            return None
        if response.is_error:
            raise ListenerError(f"listener returned HTTP {response.status_code} for {path}")
        return response.json()

    async def nodes(self) -> list[dict[str, Any]]:
        return await self._get("/api/nodes") or []

    async def containers(
        self, *, node: str | None = None, name: str | None = None, image: str | None = None
    ) -> list[dict[str, Any]]:
        params = {k: v for k, v in {"node": node, "name": name, "image": image}.items() if v}
        return await self._get("/api/containers", params) or []

    async def container(self, name: str) -> list[dict[str, Any]]:
        """Containers with exactly this name; [] if there are none."""
        return await self._get(f"/api/containers/{quote(name, safe='')}") or []
