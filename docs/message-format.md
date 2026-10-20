# Broadcast message format (schema version 1)

Every `DOCMON_INTERVAL` seconds (default 60, plus up to `DOCMON_JITTER`
seconds) each agent sends one **beat**: a UDP datagram to
`255.255.255.255:50505` holding a single compact UTF-8 JSON object.

If a node has too many containers to fit in one datagram of
`DOCMON_MAX_DATAGRAM` bytes (default 1400, which avoids IP fragmentation),
the beat is split into several datagrams. Each one is a complete message with
the same header and a slice of `containers`; `part` and `parts` say how many
there are. A listener has the full beat once it holds parts `1..parts` for
the same `node.hostname` and `seq`. A node with no containers still sends one
message, so every beat is also a heartbeat.

The code that builds and parses messages lives in
[`schema/docmon_schema`](../schema/docmon_schema/message.py).

## Example

```json
{
  "schema_version": 1,
  "node": {"hostname": "pi-2", "ip": "192.168.1.42", "agent": "0.1.0"},
  "sent_at": "2026-10-20T19:00:03+00:00",
  "interval": 60.0,
  "seq": 17,
  "part": 1,
  "parts": 1,
  "containers": [
    {
      "name": "media-jellyfin-1",
      "id": "4f2c9a1b7d3e",
      "compose_project": "media",
      "compose_service": "jellyfin",
      "image": "ghcr.io/kevinmcaleer/jellyfin:10.9",
      "image_id": "sha256:9b1e…",
      "image_digest": "sha256:c0ffee…",
      "status": "running",
      "started_at": "2026-10-20T07:12:44.123456789Z",
      "oci": {
        "source": "https://github.com/kevinmcaleer/jellyfin",
        "revision": "3e1f0c2…",
        "created": "2026-10-18T21:04:11Z"
      }
    }
  ]
}
```

## Fields

| Field | Type | Notes |
| --- | --- | --- |
| `schema_version` | int | `1`. Listeners should ignore versions they don't know. |
| `node.hostname` | string | Host's hostname, or `DOCMON_NODE_NAME`. |
| `node.ip` | string or null | Node's LAN address, or `DOCMON_NODE_IP`. |
| `node.agent` | string | Agent version. |
| `sent_at` | string | ISO 8601 UTC time the beat was built. |
| `interval` | number | Agent's configured interval in seconds, so a listener can work out when a node is stale (e.g. after 3 × `interval`). |
| `seq` | int | Beat counter. Starts at 0 when the agent starts, so it resets after a restart. |
| `part`, `parts` | int | This datagram's position in the beat, from 1. |
| `error` | string | Only present when the agent could not read Docker; `containers` is then empty. |
| `containers[]` | array | Sorted by `name`. |
| `.name` | string | Container name. |
| `.id` | string | Short (12-char) container ID. |
| `.compose_project` | string or null | From the `com.docker.compose.project` label. |
| `.compose_service` | string or null | From the `com.docker.compose.service` label. |
| `.image` | string | Image reference the container was started from. |
| `.image_id` | string | Local image ID (`sha256:…`). |
| `.image_digest` | string or null | Digest from the image's `RepoDigests` (the registry digest for pulled images); null when Docker has none, which is common for locally built images. |
| `.status` | string | Docker state: `running`, `restarting`, `paused`, `exited`, … |
| `.started_at` | string | Docker's `State.StartedAt`. |
| `.oci` | object | Any of `source`, `revision`, `created`, `version` from the `org.opencontainers.image.*` labels. Missing or empty labels are left out. |

Adding fields is backwards compatible and keeps `schema_version` at 1.
Removing or changing a field bumps it.
