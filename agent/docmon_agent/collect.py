"""Turn Docker inspect data into docmon container entries.

The functions here take plain inspect dicts so they can be tested without a
Docker daemon; ``collect_containers`` is the only part that talks to Docker.
"""

from __future__ import annotations

import logging
from typing import Any

from docmon_schema import OCI_LABELS

log = logging.getLogger(__name__)

COMPOSE_PROJECT = "com.docker.compose.project"
COMPOSE_SERVICE = "com.docker.compose.service"


def image_digest(image_attrs: dict[str, Any] | None) -> str | None:
    """Return the registry digest (``sha256:...``) of an image, if it has one.

    Locally built images have no RepoDigests, so this is often None.
    """
    if not image_attrs:
        return None
    for repo_digest in image_attrs.get("RepoDigests") or []:
        _, _, digest = repo_digest.partition("@")
        if digest:
            return digest
    return None


def container_entry(
    attrs: dict[str, Any], image_attrs: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Build one ``containers[]`` entry from ``docker inspect`` output."""
    config = attrs.get("Config") or {}
    state = attrs.get("State") or {}
    # Container labels already include the labels baked into its image.
    labels = config.get("Labels") or {}
    return {
        "name": (attrs.get("Name") or "").lstrip("/"),
        "id": (attrs.get("Id") or "")[:12],
        "compose_project": labels.get(COMPOSE_PROJECT),
        "compose_service": labels.get(COMPOSE_SERVICE),
        "image": config.get("Image"),
        "image_id": attrs.get("Image"),
        "image_digest": image_digest(image_attrs),
        "status": state.get("Status"),
        "started_at": state.get("StartedAt"),
        "oci": {key: labels[label] for key, label in OCI_LABELS.items() if labels.get(label)},
    }


def collect_containers(client: Any, include_stopped: bool = False) -> list[dict[str, Any]]:
    """Read every container on this node from the Docker API, sorted by name."""
    import docker.errors

    api = client.api
    images: dict[str, dict[str, Any] | None] = {}
    entries = []
    for summary in api.containers(all=include_stopped):
        try:
            attrs = api.inspect_container(summary["Id"])
        except docker.errors.NotFound:
            # Removed between list and inspect.
            continue
        image_id = attrs.get("Image")
        if image_id not in images:
            try:
                images[image_id] = api.inspect_image(image_id)
            except docker.errors.NotFound:
                images[image_id] = None
        entries.append(container_entry(attrs, images[image_id]))
    entries.sort(key=lambda entry: entry["name"])
    return entries
