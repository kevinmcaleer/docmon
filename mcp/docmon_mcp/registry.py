"""Read OCI provenance labels for an image straight from its registry.

Used only for images whose local labels say nothing. Works anonymously with
any registry that speaks the OCI distribution API (GHCR, Docker Hub, ...),
so it only finds public images.
"""

from __future__ import annotations

import logging
import re

import httpx
from docmon_schema import OCI_LABELS

from docmon_mcp.provenance import DOCKER_HUB, parse_image

log = logging.getLogger(__name__)

_INDEX_TYPES = (
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
)
_MANIFEST_TYPES = (
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.v2+json",
)
_ACCEPT = ", ".join(_INDEX_TYPES + _MANIFEST_TYPES)


def _pick_labels(labels: dict[str, str] | None) -> dict[str, str]:
    labels = labels or {}
    return {key: labels[name] for key, name in OCI_LABELS.items() if labels.get(name)}


def _pick_platform(manifests: list[dict], preferred: str) -> dict | None:
    """The manifest for ``preferred`` (e.g. linux/arm64), else the first real image."""
    images = [
        m
        for m in manifests
        # Buildx attaches attestations as platform unknown/unknown.
        if (m.get("platform") or {}).get("os") not in (None, "unknown")
    ]
    for m in images:
        p = m["platform"]
        name = f"{p.get('os')}/{p.get('architecture')}"
        if p.get("variant"):
            name += f"/{p['variant']}"
        if name == preferred or name.startswith(preferred + "/"):
            return m
    return images[0] if images else (manifests[0] if manifests else None)


class RegistryClient:
    def __init__(
        self, *, timeout: float = 10.0, platform: str = "linux/arm64", client=None
    ) -> None:
        self.platform = platform
        self._client = client or httpx.AsyncClient(timeout=timeout, follow_redirects=True)
        self._tokens: dict[str, str] = {}

    async def aclose(self) -> None:
        await self._client.aclose()

    async def labels(self, reference: str, digest: str | None = None) -> dict[str, str]:
        """OCI provenance labels for ``reference``, as ``{source, revision, ...}``.

        ``digest`` (the local RepoDigest) pins the exact image that is running
        rather than whatever the tag points at now. Returns {} on any failure.
        """
        image = parse_image(reference)
        host = "registry-1.docker.io" if image["registry"] == DOCKER_HUB else image["registry"]
        ref = digest or image["digest"] or image["tag"]
        base = f"https://{host}/v2/{image['repository']}"
        try:
            found: dict[str, str] = {}
            manifest = await self._get_json(f"{base}/manifests/{ref}", _ACCEPT)
            # docker/metadata-action also writes the labels as annotations.
            found.update(_pick_labels(manifest.get("annotations")))
            if manifest.get("mediaType") in _INDEX_TYPES or "manifests" in manifest:
                chosen = _pick_platform(manifest.get("manifests") or [], self.platform)
                if chosen is None:
                    return found
                manifest = await self._get_json(f"{base}/manifests/{chosen['digest']}", _ACCEPT)
                found = {**_pick_labels(manifest.get("annotations")), **found}
            config_digest = (manifest.get("config") or {}).get("digest")
            if config_digest:
                config = await self._get_json(f"{base}/blobs/{config_digest}", "*/*")
                labels = (config.get("config") or {}).get("Labels")
                found = {**found, **_pick_labels(labels)}
            return found
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            log.info("registry lookup for %s failed: %s", reference, exc)
            return {}

    async def _get_json(self, url: str, accept: str) -> dict:
        # Tokens are scoped to one repository, so cache them per repository.
        repo = re.sub(r"/(manifests|blobs)/[^/]+$", "", url)
        headers = {"Accept": accept}
        if token := self._tokens.get(repo):
            headers["Authorization"] = f"Bearer {token}"
        response = await self._client.get(url, headers=headers)
        if response.status_code == 401 and (challenge := response.headers.get("www-authenticate")):
            self._tokens[repo] = await self._token(challenge)
            headers["Authorization"] = f"Bearer {self._tokens[repo]}"
            response = await self._client.get(url, headers=headers)
        response.raise_for_status()
        return response.json()

    async def _token(self, challenge: str) -> str:
        """Anonymous bearer token from a ``WWW-Authenticate: Bearer realm=...`` challenge."""
        params = dict(re.findall(r'(\w+)="([^"]*)"', challenge))
        realm = params.pop("realm", None)
        if not realm:
            raise ValueError(f"unsupported auth challenge {challenge!r}")
        response = await self._client.get(realm, params=params)
        response.raise_for_status()
        body = response.json()
        return body.get("token") or body["access_token"]
