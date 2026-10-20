from docmon_agent.collect import container_entry, image_digest
from docmon_agent.config import Config

ATTRS = {
    "Id": "0123456789abcdef0123",
    "Name": "/stack-web-1",
    "Image": "sha256:" + "a" * 64,
    "Config": {
        "Image": "ghcr.io/kev/web:1.2",
        "Labels": {
            "com.docker.compose.project": "stack",
            "com.docker.compose.service": "web",
            "org.opencontainers.image.source": "https://github.com/kev/web",
            "org.opencontainers.image.revision": "abc123",
            "org.opencontainers.image.created": "2026-10-01T00:00:00Z",
            "org.opencontainers.image.version": "",
            "unrelated": "ignored",
        },
    },
    "State": {"Status": "running", "StartedAt": "2026-10-20T18:00:00Z"},
}


def test_container_entry_maps_inspect_fields():
    image = {"RepoDigests": ["ghcr.io/kev/web@sha256:" + "d" * 64]}
    assert container_entry(ATTRS, image) == {
        "name": "stack-web-1",
        "id": "0123456789ab",
        "compose_project": "stack",
        "compose_service": "web",
        "image": "ghcr.io/kev/web:1.2",
        "image_id": "sha256:" + "a" * 64,
        "image_digest": "sha256:" + "d" * 64,
        "status": "running",
        "started_at": "2026-10-20T18:00:00Z",
        # Empty labels are dropped.
        "oci": {
            "source": "https://github.com/kev/web",
            "revision": "abc123",
            "created": "2026-10-01T00:00:00Z",
        },
    }


def test_container_entry_tolerates_missing_fields():
    entry = container_entry({"Name": "/bare"})
    assert entry["name"] == "bare"
    assert entry["compose_project"] is None
    assert entry["image_digest"] is None
    assert entry["oci"] == {}


def test_image_digest_for_local_build_is_none():
    assert image_digest({"RepoDigests": []}) is None
    assert image_digest(None) is None


def test_config_from_env():
    config = Config.from_env(
        {"DOCMON_PORT": "6000", "DOCMON_INTERVAL": "30", "DOCMON_INCLUDE_STOPPED": "yes"}
    )
    assert (config.port, config.interval, config.include_stopped) == (6000, 30.0, True)
    assert Config.from_env({}) == Config()
