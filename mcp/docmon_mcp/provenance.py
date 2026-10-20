"""Work out where an image came from: repo, commit and commit URL.

Everything here is pure so it can be tested without a listener or registry.
"""

from __future__ import annotations

import re
from typing import Any

DOCKER_HUB = "docker.io"

# Hosts whose commit pages live at <repo>/commit/<sha>. GitLab uses /-/commit/
# and Bitbucket /commits/; anything else gets the GitHub-style path, which is
# also what Gitea, Forgejo and Codeberg use.
_COMMIT_PATHS = {
    "gitlab.com": "/-/commit/",
    "bitbucket.org": "/commits/",
}


def normalize_source(source: str | None) -> str | None:
    """Turn ``git@host:owner/repo.git`` and friends into an https URL."""
    if not source:
        return None
    url = source.strip()
    if match := re.fullmatch(r"(?:ssh://)?git@([^:/]+)[:/](.+)", url):
        url = f"https://{match.group(1)}/{match.group(2)}"
    elif url.startswith("git://"):
        url = "https://" + url[len("git://") :]
    elif url.startswith("http://"):
        url = "https://" + url[len("http://") :]
    elif not url.startswith("https://"):
        # A bare "github.com/owner/repo".
        url = "https://" + url
    url = url.rstrip("/")
    if url.endswith(".git"):
        url = url[: -len(".git")]
    return url


def commit_url(source: str | None, revision: str | None) -> str | None:
    """Link to ``revision`` in the repo at ``source``, or None if either is missing."""
    repo = normalize_source(source)
    if not repo or not revision or not re.fullmatch(r"[0-9a-fA-F]{7,64}", revision):
        return None
    host = repo.split("/")[2].lower()
    return f"{repo}{_COMMIT_PATHS.get(host, '/commit/')}{revision}"


def parse_image(reference: str) -> dict[str, str | None]:
    """Split an image reference into registry, repository, tag and digest.

    Follows Docker's rules: the first path part is a registry only if it
    contains a ``.`` or ``:`` or is ``localhost``; Docker Hub names without a
    namespace live under ``library/``.
    """
    rest, _, digest = reference.partition("@")
    tag = None
    slash = rest.rfind("/")
    colon = rest.rfind(":")
    if colon > slash:
        rest, tag = rest[:colon], rest[colon + 1 :]
    first, sep, remainder = rest.partition("/")
    if sep and ("." in first or ":" in first or first == "localhost"):
        registry, repository = first, remainder
    else:
        registry, repository = DOCKER_HUB, rest
    if registry in ("docker.io", "index.docker.io", "registry-1.docker.io"):
        registry = DOCKER_HUB
        if "/" not in repository:
            repository = f"library/{repository}"
    return {
        "registry": registry,
        "repository": repository,
        "tag": tag or (None if digest else "latest"),
        "digest": digest or None,
    }


def guess_source(image: dict[str, str | None]) -> str | None:
    """Best guess at a repo from the image name alone, e.g. GHCR's owner/name."""
    if image["registry"] == "ghcr.io" and image["repository"]:
        parts = image["repository"].split("/")
        if len(parts) >= 2:
            return f"https://github.com/{parts[0]}/{parts[1]}"
    return None


def image_page(image: dict[str, str | None]) -> str | None:
    """Web page for the image on its registry, where there is a well-known one."""
    registry, repository = image["registry"], image["repository"]
    if registry == DOCKER_HUB:
        if repository.startswith("library/"):
            return f"https://hub.docker.com/_/{repository[len('library/') :]}"
        return f"https://hub.docker.com/r/{repository}"
    if registry in ("ghcr.io", "quay.io"):
        # ghcr.io redirects a browser to the package's page on GitHub.
        return f"https://{registry}/{repository}"
    return None


def provenance(
    container: dict[str, Any], registry_labels: dict[str, str] | None = None
) -> dict[str, Any]:
    """Provenance for one container entry from the listener.

    ``registry_labels`` are the ``org.opencontainers.image.*`` labels looked up
    from the registry, used only for fields the local image labels lack.
    """
    oci = {k: v for k, v in (container.get("oci") or {}).items() if v}
    local = bool(oci)
    from_registry = []
    for key, value in (registry_labels or {}).items():
        if value and not oci.get(key):
            oci[key] = value
            from_registry.append(key)

    image = parse_image(str(container.get("image") or ""))
    source = normalize_source(oci.get("source"))
    revision = oci.get("revision") or None
    result: dict[str, Any] = {
        "image": container.get("image"),
        "registry": image["registry"],
        "repository": image["repository"],
        "tag": image["tag"],
        "image_digest": container.get("image_digest"),
        "image_id": container.get("image_id"),
        "image_page": image_page(image),
        "source": source,
        "revision": revision,
        "commit_url": commit_url(source, revision),
        "created": oci.get("created") or None,
        "version": oci.get("version") or None,
        "labels_from": _labels_from(local, from_registry),
    }
    if source and revision:
        result["known"] = True
        result["note"] = "Built from the commit above (from OCI labels)."
    elif source:
        result["known"] = "partial"
        result["note"] = "The repo is known from OCI labels, but the commit is not."
    else:
        result["known"] = False
        guess = guess_source(image)
        result["guessed_source"] = guess
        result["note"] = (
            "Provenance unknown: the image has no org.opencontainers.image.source label."
            + (f" Going by the image name only, the code may live at {guess}." if guess else "")
        )
    return result


def _labels_from(local: bool, from_registry: list[str]) -> str | None:
    if from_registry:
        return "image+registry" if local else "registry"
    return "image" if local else None
