import asyncio
import socket

import pytest
from docmon_listener.app import create_app
from docmon_listener.config import Config
from docmon_listener.state import State, parse_started_at
from docmon_listener.udp import start
from docmon_schema import build_messages, encode
from fastapi.testclient import TestClient


class Clock:
    def __init__(self, now=1_800_000_000.0):
        self.now = now

    def __call__(self):
        return self.now


def container(name, **extra):
    return {
        "name": name,
        "id": "0" * 12,
        "compose_project": "stack",
        "compose_service": name,
        "image": f"ghcr.io/kev/{name}:1.0",
        "image_id": "sha256:" + "a" * 64,
        "image_digest": None,
        "status": "running",
        "started_at": "2027-01-15T07:00:00.123456789Z",
        "oci": {"source": f"https://github.com/kev/{name}", "revision": "c" * 40},
        **extra,
    }


def beat(hostname, containers, *, seq=0, interval=60.0, max_bytes=1400, error=None):
    return build_messages(
        node={"hostname": hostname, "ip": "192.168.1.10", "agent": "0.1.0"},
        containers=containers,
        sent_at="2027-01-15T08:00:00+00:00",
        seq=seq,
        interval=interval,
        error=error,
        max_bytes=max_bytes,
    )


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def state(clock):
    return State(clock=clock)


def test_single_part_beat_is_stored(state):
    [message] = beat("pi-1", [container("web"), container("db")])
    assert state.accept(message, "192.168.1.10")
    [node] = state.nodes()
    assert node["hostname"] == "pi-1"
    assert node["status"] == "online"
    assert node["container_count"] == 2
    assert [c["name"] for c in state.containers()] == ["db", "web"]


def test_split_beat_waits_for_all_parts_in_any_order(state):
    containers = [container(f"svc-{i:02d}") for i in range(30)]
    messages = beat("pi-1", containers, max_bytes=1400)
    assert len(messages) > 2
    for message in reversed(messages[1:]):
        assert not state.accept(message)
    assert state.containers() == []
    assert state.accept(messages[0])
    assert [c["name"] for c in state.containers()] == [c["name"] for c in containers]


def test_new_beat_replaces_previous(state):
    state.accept(beat("pi-1", [container("old")], seq=1)[0])
    state.accept(beat("pi-1", [container("new")], seq=2)[0])
    assert [c["name"] for c in state.containers()] == ["new"]


def test_incomplete_beat_keeps_old_containers_but_counts_as_seen(state, clock):
    state.accept(beat("pi-1", [container("web")], seq=1)[0])
    clock.now += 200  # would be stale by now
    partial = beat("pi-1", [container(f"svc-{i:02d}") for i in range(30)], seq=2)
    state.accept(partial[0])
    assert state.nodes()[0]["status"] == "online"
    assert [c["name"] for c in state.containers()] == ["web"]


def test_stale_after_three_missed_intervals_then_gone(clock):
    state = State(clock=clock, stale_after=3, gone_after=600)
    state.accept(beat("pi-1", [], interval=60)[0])
    clock.now += 179
    assert state.nodes()[0]["status"] == "online"
    clock.now += 2
    assert state.nodes()[0]["status"] == "stale"
    assert state.containers(node="pi-1") == []  # empty beat is still a heartbeat
    clock.now += 600
    assert state.nodes()[0]["status"] == "gone"


def test_error_is_reported(state):
    state.accept(beat("pi-1", [], error="docker: socket missing")[0])
    assert state.nodes()[0]["error"] == "docker: socket missing"


@pytest.mark.parametrize(
    "message",
    [
        {"schema_version": 1},
        {
            "schema_version": 1,
            "node": {"hostname": "x"},
            "seq": 0,
            "part": 2,
            "parts": 1,
            "containers": [],
        },
        {
            "schema_version": 1,
            "node": {"hostname": "x"},
            "seq": 0,
            "part": 1,
            "parts": 1,
            "containers": "nope",
        },
    ],
)
def test_invalid_messages_are_rejected(state, message):
    with pytest.raises(ValueError):
        state.accept(message)


def test_filters(state):
    state.accept(beat("pi-1", [container("web"), container("db")])[0])
    state.accept(beat("pi-2", [container("web-2")])[0])
    assert {c["node"] for c in state.containers(name="WEB")} == {"pi-1", "pi-2"}
    assert [c["name"] for c in state.containers(node="pi-1", image="kev/db")] == ["db"]


def test_uptime_from_docker_nanoseconds(state, clock):
    started = parse_started_at("2027-01-15T07:00:00.123456789Z")
    assert started is not None and started.microsecond == 123456
    assert parse_started_at("0001-01-01T00:00:00Z") is None
    clock.now = started.timestamp() + 3600
    state.accept(beat("pi-1", [container("web")])[0])
    assert state.containers()[0]["uptime_seconds"] == 3600


def test_state_persists_to_sqlite(tmp_path, clock):
    db = str(tmp_path / "state.sqlite")
    State(clock=clock, db=db).accept(beat("pi-1", [container("web")])[0])
    restored = State(clock=clock, db=db)
    assert [c["name"] for c in restored.containers()] == ["web"]
    assert restored.forget("pi-1")
    assert State(clock=clock, db=db).nodes() == []


def test_api(state):
    state.accept(beat("pi-1", [container("web")])[0])
    state.accept(beat("pi-2", [container("web"), container("db")])[0])
    with TestClient(create_app(Config(), state, listen=False)) as client:
        assert "docmon" in client.get("/").text
        assert [n["hostname"] for n in client.get("/api/nodes").json()] == ["pi-1", "pi-2"]
        assert len(client.get("/api/containers").json()) == 3
        assert len(client.get("/api/containers", params={"node": "pi-2"}).json()) == 2
        web = client.get("/api/containers/web").json()
        assert [c["node"] for c in web] == ["pi-1", "pi-2"]
        assert web[0]["oci"]["source"] == "https://github.com/kev/web"
        assert client.get("/api/containers/nope").status_code == 404
        assert client.delete("/api/nodes/pi-1").status_code == 204
        assert client.delete("/api/nodes/pi-1").status_code == 404


def test_udp_end_to_end(state):
    async def run():
        transport = await start(state, "127.0.0.1", 0)
        port = transport.get_extra_info("sockname")[1]
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.sendto(b"not json", ("127.0.0.1", port))
            for message in beat("pi-1", [container(f"svc-{i:02d}") for i in range(20)]):
                sock.sendto(encode(message), ("127.0.0.1", port))
        for _ in range(50):
            if state.nodes():
                break
            await asyncio.sleep(0.02)
        transport.close()

    asyncio.run(run())
    assert len(state.containers()) == 20
