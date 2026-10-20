import asyncio

import httpx
import pytest
from docmon_listener.app import create_app
from docmon_listener.config import Config as ListenerConfig
from docmon_listener.state import State
from docmon_mcp.client import ListenerClient, ListenerError
from docmon_mcp.config import Config
from docmon_mcp.provenance import commit_url, normalize_source, parse_image, provenance
from docmon_mcp.registry import RegistryClient
from docmon_mcp.server import create_server
from mcp.server.mcpserver.exceptions import ToolError
from test_listener import Clock, beat, container

SHA = "3e1f0c2" + "a" * 33


# -- provenance ---------------------------------------------------------------


@pytest.mark.parametrize(
    "source, expected",
    [
        ("https://github.com/kev/app", "https://github.com/kev/app"),
        ("https://github.com/kev/app.git", "https://github.com/kev/app"),
        ("git@github.com:kev/app.git", "https://github.com/kev/app"),
        ("ssh://git@gitlab.com/kev/app.git", "https://gitlab.com/kev/app"),
        ("github.com/kev/app/", "https://github.com/kev/app"),
        ("", None),
        (None, None),
    ],
)
def test_normalize_source(source, expected):
    assert normalize_source(source) == expected


def test_commit_url_per_host():
    assert (
        commit_url("https://github.com/kev/app", SHA) == f"https://github.com/kev/app/commit/{SHA}"
    )
    assert (
        commit_url("https://gitlab.com/kev/app", SHA)
        == f"https://gitlab.com/kev/app/-/commit/{SHA}"
    )
    assert (
        commit_url("https://bitbucket.org/k/a", SHA) == f"https://bitbucket.org/k/a/commits/{SHA}"
    )
    assert commit_url("https://github.com/kev/app", None) is None
    assert commit_url(None, SHA) is None
    # A revision that isn't a SHA (e.g. a branch name) doesn't make a commit link.
    assert commit_url("https://github.com/kev/app", "main") is None


@pytest.mark.parametrize(
    "reference, registry, repository, tag, digest",
    [
        ("nginx", "docker.io", "library/nginx", "latest", None),
        ("nginx:1.27", "docker.io", "library/nginx", "1.27", None),
        ("grafana/grafana:11", "docker.io", "grafana/grafana", "11", None),
        ("ghcr.io/kev/app:1.0", "ghcr.io", "kev/app", "1.0", None),
        ("localhost:5000/app", "localhost:5000", "app", "latest", None),
        ("ghcr.io/kev/app@sha256:abc", "ghcr.io", "kev/app", None, "sha256:abc"),
    ],
)
def test_parse_image(reference, registry, repository, tag, digest):
    assert parse_image(reference) == {
        "registry": registry,
        "repository": repository,
        "tag": tag,
        "digest": digest,
    }


def test_provenance_with_labels():
    result = provenance(container("web"))
    assert result["known"] is True
    assert result["source"] == "https://github.com/kev/web"
    assert result["commit_url"] == "https://github.com/kev/web/commit/" + "c" * 40
    assert result["labels_from"] == "image"


def test_provenance_without_labels_says_unknown():
    result = provenance(container("web", image="ghcr.io/kev/web:1", oci={}))
    assert result["known"] is False
    assert result["source"] is None
    assert result["guessed_source"] == "https://github.com/kev/web"
    assert "unknown" in result["note"]
    assert result["image_page"] == "https://ghcr.io/kev/web"


def test_provenance_fills_gaps_from_registry():
    c = container("web", oci={"source": "https://github.com/kev/web"})
    result = provenance(c, {"source": "https://github.com/other/x", "revision": SHA})
    # Local labels win; the registry only fills what is missing.
    assert result["source"] == "https://github.com/kev/web"
    assert result["revision"] == SHA
    assert result["labels_from"] == "image+registry"


# -- registry -----------------------------------------------------------------


def registry_transport(requests):
    index = {
        "mediaType": "application/vnd.oci.image.index.v1+json",
        "manifests": [
            {"digest": "sha256:amd", "platform": {"os": "linux", "architecture": "amd64"}},
            {"digest": "sha256:arm", "platform": {"os": "linux", "architecture": "arm64"}},
            {"digest": "sha256:att", "platform": {"os": "unknown", "architecture": "unknown"}},
        ],
        "annotations": {"org.opencontainers.image.created": "2026-10-18T21:04:11Z"},
    }
    manifests = {
        "sha256:arm": {
            "mediaType": "application/vnd.oci.image.manifest.v1+json",
            "config": {"digest": "sha256:cfg"},
        }
    }
    config = {
        "config": {
            "Labels": {
                "org.opencontainers.image.source": "https://github.com/kev/web",
                "org.opencontainers.image.revision": SHA,
            }
        }
    }

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        if request.url.host == "ghcr.io" and request.url.path == "/token":
            return httpx.Response(200, json={"token": "t0k"})
        if request.headers.get("authorization") != "Bearer t0k":
            return httpx.Response(
                401,
                headers={
                    "www-authenticate": 'Bearer realm="https://ghcr.io/token",'
                    'service="ghcr.io",scope="repository:kev/web:pull"'
                },
            )
        path = request.url.path
        if path == "/v2/kev/web/manifests/1.0":
            return httpx.Response(200, json=index)
        if path.startswith("/v2/kev/web/manifests/"):
            return httpx.Response(200, json=manifests[path.rsplit("/", 1)[1]])
        if path == "/v2/kev/web/blobs/sha256:cfg":
            return httpx.Response(200, json=config)
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def test_registry_labels_from_multi_arch_image():
    requests = []

    async def run():
        client = httpx.AsyncClient(transport=registry_transport(requests))
        return await RegistryClient(client=client).labels("ghcr.io/kev/web:1.0")

    labels = asyncio.run(run())
    assert labels == {
        "source": "https://github.com/kev/web",
        "revision": SHA,
        "created": "2026-10-18T21:04:11Z",
    }
    assert any("scope=repository" in r for r in requests)
    assert any(r.endswith("/manifests/sha256:arm") for r in requests)


def test_registry_failure_returns_nothing():
    async def run():
        client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(500)))
        return await RegistryClient(client=client).labels("ghcr.io/kev/web:1.0")

    assert asyncio.run(run()) == {}


# -- tools, end to end against the real listener API ---------------------------


class FakeRegistry:
    def __init__(self, labels):
        self.labels_for = labels
        self.calls = []

    async def labels(self, reference, digest=None):
        self.calls.append(reference)
        return self.labels_for.get(reference, {})


@pytest.fixture
def listener_state():
    state = State(clock=Clock())
    for message in beat(
        "pi-1",
        [container("grafana"), container("web", image="nginx:1.27", oci={})],
    ):
        state.accept(message)
    for message in beat("pi-2", [container("web", image="nginx:1.27", oci={})]):
        state.accept(message)
    return state


def make_server(state, registry=None):
    app = create_app(ListenerConfig(), state, listen=False)
    http = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://listener")
    listener = ListenerClient("http://listener", client=http)
    return create_server(Config(registry_lookup=False), listener=listener, registry=registry)


def call(server, tool, **arguments):
    result = asyncio.run(server.call_tool(tool, arguments))
    assert not result.is_error, result
    structured = result.structured_content
    return structured.get("result", structured)


def test_tools_are_listed(listener_state):
    tools = asyncio.run(make_server(listener_state).list_tools())
    assert {t.name for t in tools} == {
        "list_nodes",
        "list_containers",
        "find_container",
        "get_image_provenance",
    }


def test_list_nodes(listener_state):
    nodes = call(make_server(listener_state), "list_nodes")
    assert [(n["hostname"], n["status"], n["container_count"]) for n in nodes] == [
        ("pi-1", "online", 2),
        ("pi-2", "online", 1),
    ]


def test_list_containers_on_a_node(listener_state):
    rows = call(make_server(listener_state), "list_containers", node="pi-1")
    assert [(r["name"], r["node"], r["status"]) for r in rows] == [
        ("grafana", "pi-1", "running"),
        ("web", "pi-1", "running"),
    ]
    assert rows[0]["source"] == "https://github.com/kev/grafana"


def test_find_container_exact_and_substring(listener_state):
    server = make_server(listener_state)
    found = call(server, "find_container", name="web")
    assert found["match"] == "exact"
    assert sorted(c["node"] for c in found["containers"]) == ["pi-1", "pi-2"]

    found = call(server, "find_container", name="GRAF")
    assert found["match"] == "substring"
    assert [c["name"] for c in found["containers"]] == ["grafana"]

    assert call(server, "find_container", name="nope")["match"] == "none"


def test_where_is_x_running_and_what_repo(listener_state):
    """The issue's acceptance check: node, status, repo URL and commit."""
    result = call(make_server(listener_state), "get_image_provenance", container="grafana")
    [answer] = result["results"]
    assert answer["node"] == "pi-1"
    assert answer["node_status"] == "online"
    assert answer["status"] == "running"
    assert answer["source"] == "https://github.com/kev/grafana"
    assert answer["revision"] == "c" * 40
    assert answer["commit_url"] == "https://github.com/kev/grafana/commit/" + "c" * 40
    assert answer["known"] is True


def test_provenance_by_image_groups_nodes_and_uses_registry(listener_state):
    registry = FakeRegistry({"nginx:1.27": {"source": "https://github.com/nginx/docker-nginx"}})
    result = call(make_server(listener_state, registry), "get_image_provenance", image="nginx")
    [answer] = result["results"]
    assert answer["node"] == "pi-1"
    assert answer["also_running"] == [{"container": "web", "node": "pi-2"}]
    assert answer["source"] == "https://github.com/nginx/docker-nginx"
    assert answer["known"] == "partial"
    assert answer["labels_from"] == "registry"
    assert registry.calls == ["nginx:1.27"]


def test_provenance_unknown_is_said_clearly(listener_state):
    result = call(make_server(listener_state), "get_image_provenance", container="web", node="pi-2")
    [answer] = result["results"]
    assert answer["known"] is False
    assert answer["registry"] == "docker.io"
    assert answer["repository"] == "library/nginx"
    assert answer["image_page"] == "https://hub.docker.com/_/nginx"
    assert "unknown" in answer["note"]


def test_provenance_for_image_not_running(listener_state):
    registry = FakeRegistry({"ghcr.io/kev/new:2": {"source": "https://github.com/kev/new"}})
    result = call(
        make_server(listener_state, registry), "get_image_provenance", image="ghcr.io/kev/new:2"
    )
    [answer] = result["results"]
    assert answer["running"] is False
    assert answer["source"] == "https://github.com/kev/new"


def test_provenance_needs_an_argument(listener_state):
    with pytest.raises(ToolError, match="container name or an image"):
        asyncio.run(make_server(listener_state).call_tool("get_image_provenance", {}))


def test_unreachable_listener_is_reported():
    def refuse(request):
        raise httpx.ConnectError("refused", request=request)

    http = httpx.AsyncClient(transport=httpx.MockTransport(refuse))
    server = create_server(
        Config(registry_lookup=False), listener=ListenerClient("http://pi-1:8080", client=http)
    )
    with pytest.raises(ToolError, match="cannot reach the docmon listener at http://pi-1:8080"):
        asyncio.run(server.call_tool("list_nodes", {}))
    assert issubclass(ListenerError, ToolError)


def test_config_from_env():
    config = Config.from_env(
        {
            "DOCMON_LISTENER_URL": "http://pi-1:8080/",
            "DOCMON_MCP_TRANSPORT": "HTTP",
            "DOCMON_MCP_PORT": "9000",
            "DOCMON_REGISTRY_LOOKUP": "false",
            "DOCMON_MCP_ALLOWED_HOSTS": "pi-1:*, 192.168.1.10:*",
        }
    )
    assert config.listener_url == "http://pi-1:8080"
    assert config.transport == "http"
    assert config.http_port == 9000
    assert config.registry_lookup is False
    assert config.allowed_hosts == ("pi-1:*", "192.168.1.10:*")
