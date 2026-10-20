"""The MCP tools, built on the listener's JSON API."""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field
from starlette.requests import Request
from starlette.responses import JSONResponse

from docmon_mcp import __version__
from docmon_mcp.client import ListenerClient
from docmon_mcp.config import Config
from docmon_mcp.provenance import parse_image, provenance
from docmon_mcp.registry import RegistryClient

INSTRUCTIONS = """\
docmon knows which Docker containers run on which node of a small LAN cluster
(often Raspberry Pis), from broadcasts each node's agent sends about once a
minute. Use list_nodes for the nodes and whether they are online, stale or gone;
list_containers for what runs on a node; find_container for where a container
runs; and get_image_provenance for the repo and commit an image was built from.
A node that is stale or gone may no longer be running what it last reported.
"""


def _summary(container: dict[str, Any]) -> dict[str, Any]:
    """The fields worth showing for a container, without the raw label dump."""
    oci = container.get("oci") or {}
    return {
        "name": container.get("name"),
        "node": container.get("node"),
        "node_status": container.get("node_status"),
        "status": container.get("status"),
        "uptime_seconds": container.get("uptime_seconds"),
        "image": container.get("image"),
        "compose_project": container.get("compose_project"),
        "compose_service": container.get("compose_service"),
        "source": oci.get("source"),
        "revision": oci.get("revision"),
    }


def _same_image(container: dict[str, Any], image: str) -> bool:
    """Whether ``image`` names the container's image, ignoring a defaulted tag."""
    if container.get("image") == image:
        return True
    want, have = parse_image(image), parse_image(str(container.get("image") or ""))
    if (want["registry"], want["repository"]) != (have["registry"], have["repository"]):
        return False
    if want["digest"]:
        return want["digest"] == container.get("image_digest") or want["digest"] == have["digest"]
    # "nginx" means any tag only if the caller left the tag off.
    return ":" not in image.rsplit("/", 1)[-1] or want["tag"] == have["tag"]


def create_server(
    config: Config,
    *,
    listener: ListenerClient | None = None,
    registry: RegistryClient | None = None,
) -> MCPServer:
    listener = listener or ListenerClient(config.listener_url, timeout=config.timeout)
    if registry is None and config.registry_lookup:
        registry = RegistryClient(timeout=config.timeout, platform=config.platform)

    server = MCPServer(
        "docmon",
        instructions=INSTRUCTIONS,
        version=__version__,
        log_level=config.log_level,
    )

    @server.custom_route("/healthz", methods=["GET"], include_in_schema=False)
    async def healthz(request: Request) -> JSONResponse:
        return JSONResponse({"ok": True})

    async def resolve(container: dict[str, Any]) -> dict[str, Any]:
        labels = None
        has_source = (container.get("oci") or {}).get("source")
        if registry is not None and not has_source and container.get("image"):
            labels = await registry.labels(container["image"], container.get("image_digest"))
        result = provenance(container, labels)
        result.update(
            container=container.get("name"),
            node=container.get("node"),
            node_status=container.get("node_status"),
            status=container.get("status"),
        )
        return result

    @server.tool()
    async def list_nodes() -> list[dict[str, Any]]:
        """List every node docmon has heard from, with its status (online, stale or
        gone), IP, when it was last seen and how many containers it reported."""
        return await listener.nodes()

    @server.tool()
    async def list_containers(
        node: Annotated[
            str | None, Field(description="Only this node's containers (exact hostname)")
        ] = None,
        image: Annotated[
            str | None, Field(description="Only containers whose image contains this text")
        ] = None,
    ) -> list[dict[str, Any]]:
        """List containers across the cluster, or on one node: name, node, status,
        uptime, image, compose project/service, and the image's repo and commit if
        its OCI labels have them."""
        return [_summary(c) for c in await listener.containers(node=node, image=image)]

    @server.tool()
    async def find_container(
        name: Annotated[str, Field(description="Container name, or part of one")],
    ) -> dict[str, Any]:
        """Find which node(s) a container runs on. Exact name matches are returned
        if there are any, otherwise every container whose name contains ``name``.
        Each match includes the image's repo and commit when known."""
        exact = await listener.container(name)
        matches = exact or await listener.containers(name=name)
        return {
            "query": name,
            "match": "exact" if exact else "substring" if matches else "none",
            "containers": [_summary(c) for c in matches],
        }

    @server.tool()
    async def get_image_provenance(
        container: Annotated[
            str | None, Field(description="Container name (exact, or part of one)")
        ] = None,
        image: Annotated[
            str | None,
            Field(description="Image reference, e.g. ghcr.io/owner/app:1.2 or nginx"),
        ] = None,
        node: Annotated[str | None, Field(description="Only look on this node")] = None,
    ) -> dict[str, Any]:
        """Say where an image was built: source repo, commit, commit URL, build time,
        version and digest, from its OCI labels (looked up in the registry when the
        local image has none). Give a container name or an image reference. When
        provenance is unknown the result says so and gives the registry and image
        name instead."""
        if not container and not image:
            raise ToolError("give a container name or an image reference")
        if container:
            found = await listener.container(container) or await listener.containers(name=container)
            if node:
                found = [c for c in found if c.get("node") == node]
            how = f"container {container!r}"
        else:
            found = [
                c
                for c in await listener.containers(node=node, image=image)
                if _same_image(c, image)
            ]
            how = f"image {image!r}"

        if not found and image:
            # Not running anywhere docmon can see; the registry may still know it.
            labels = await registry.labels(image) if registry is not None else None
            result = provenance({"image": image}, labels)
            result["running"] = False
            return {"query": how, "results": [result]}
        if not found:
            return {"query": how, "results": [], "note": f"no {how} is running on any node"}

        # The same image on several nodes resolves to one answer per distinct image.
        results, seen = [], {}
        for c in found:
            key = (c.get("image"), c.get("image_id"))
            if key in seen:
                seen[key].setdefault("also_running", []).append(
                    {"container": c.get("name"), "node": c.get("node")}
                )
                continue
            result = seen[key] = await resolve(c)
            results.append(result)
        return {"query": how, "results": results}

    return server
