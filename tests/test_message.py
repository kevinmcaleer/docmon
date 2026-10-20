import json

import pytest
from docmon_schema import SCHEMA_VERSION, build_messages, decode, encode

NODE = {"hostname": "pi-1", "ip": "192.168.1.10", "agent": "0.1.0"}


def container(i, extra=""):
    return {
        "name": f"svc-{i}{extra}",
        "id": f"{i:012d}",
        "compose_project": "stack",
        "compose_service": f"svc-{i}",
        "image": f"ghcr.io/example/svc-{i}:latest",
        "image_id": "sha256:" + "a" * 64,
        "image_digest": "sha256:" + "b" * 64,
        "status": "running",
        "started_at": "2026-10-20T18:00:00.000000000Z",
        "oci": {"source": "https://github.com/example/svc", "revision": "c" * 40},
    }


def build(containers, **kwargs):
    return build_messages(
        node=NODE,
        containers=containers,
        sent_at="2026-10-20T19:00:00+00:00",
        seq=7,
        interval=60.0,
        **kwargs,
    )


def test_single_message_has_header_and_containers():
    [message] = build([container(1), container(2)])
    assert message["schema_version"] == SCHEMA_VERSION
    assert message["node"] == NODE
    assert message["seq"] == 7
    assert (message["part"], message["parts"]) == (1, 1)
    assert [c["name"] for c in message["containers"]] == ["svc-1", "svc-2"]


def test_empty_beat_still_sends_heartbeat():
    [message] = build([], error="docker: down")
    assert message["containers"] == []
    assert message["error"] == "docker: down"


@pytest.mark.parametrize("count", [5, 20, 60])
def test_large_beats_split_under_limit_and_keep_every_container(count):
    containers = [container(i) for i in range(count)]
    messages = build(containers, max_bytes=1400)
    assert all(len(encode(m)) <= 1400 for m in messages)
    assert [m["part"] for m in messages] == list(range(1, len(messages) + 1))
    assert {m["parts"] for m in messages} == {len(messages)}
    assert [c for m in messages for c in m["containers"]] == containers
    if count >= 20:
        assert len(messages) > 1


def test_oversized_container_is_sent_alone(caplog):
    big = container(0, extra="x" * 2000)
    messages = build([container(1), big, container(2)], max_bytes=1400)
    assert [len(m["containers"]) for m in messages] == [1, 1, 1]
    assert "exceeds" in caplog.text


def test_encode_decode_round_trip():
    [message] = build([container(1)])
    data = encode(message)
    assert b" " not in data.split(b'"containers"')[0]  # compact separators
    assert decode(data) == message


@pytest.mark.parametrize(
    "payload", [b"[]", b'{"hello": 1}', json.dumps({"schema_version": 99}).encode()]
)
def test_decode_rejects_foreign_payloads(payload):
    with pytest.raises(ValueError):
        decode(payload)
