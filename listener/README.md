# docmon listener

Collects the agent broadcasts (UDP 50505, see
[docs/message-format.md](../docs/message-format.md)) and shows what is running
on which node, as a web page and a JSON API. Run one copy on any node:

```sh
docker compose -f examples/compose/listener.yaml up -d
```

Then open `http://<that-node>:8080`. The page groups containers by node and
shows status, uptime, image and the source repo and commit from the image's
OCI labels. It refreshes every 10 seconds.

**By image** (the toggle at the top, or `/#images`) switches to one row per
image with a column per node. A green tick shows the image is running on that
node, and a small number shows how many containers use it there. An amber tick
means some of them aren't running, ↻ means restarting and ✕ means stopped.
Hover a cell to see the container names. If the same image tag runs different
commits on different nodes, the source column flags the number of revisions.

A node is **online** while datagrams keep arriving, **stale** after
`DOCMON_STALE_AFTER` of its own intervals pass without one (3 minutes with the
default 60s agent), and **gone** after `DOCMON_GONE_AFTER` seconds. Gone nodes
stay listed, greyed out, until you remove them with
`curl -X DELETE http://<listener>:8080/api/nodes/<hostname>`.

State is kept in SQLite at `/data/docmon.sqlite` (a named volume in the compose
example), so the list survives restarts.

## JSON API

| Endpoint | Returns |
| --- | --- |
| `GET /api/nodes` | Every node with `status` (`online`, `stale`, `gone`), `last_seen`, `ip`, `error` and `container_count` |
| `GET /api/containers` | Every container, each with its `node` and `node_status`. Filter with `?node=`, `?name=` and `?image=` (name and image match substrings, case-insensitively) |
| `GET /api/containers/{name}` | Containers with exactly this name, as a list because the same name can run on several nodes; 404 if none |
| `DELETE /api/nodes/{hostname}` | Forget a node |
| `GET /docs` | Interactive API docs |

Container entries carry every field the agent sent (including `oci.source` and
`oci.revision`) plus `uptime_seconds`.

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `DOCMON_PORT` | `50505` | UDP port to listen on |
| `DOCMON_BIND` | `0.0.0.0` | Address to listen for broadcasts on |
| `DOCMON_HTTP_PORT` | `8080` | Port for the web page and API |
| `DOCMON_HTTP_HOST` | `0.0.0.0` | Address for the web page and API |
| `DOCMON_STALE_AFTER` | `3` | Missed agent intervals before a node is stale |
| `DOCMON_GONE_AFTER` | `3600` | Seconds of silence before a node is gone; `0` never |
| `DOCMON_DB` | `/data/docmon.sqlite` in the image | SQLite file for state; empty keeps it in memory |
| `DOCMON_LOG_LEVEL` | `INFO` | `DEBUG` logs every beat and every rejected datagram |

`network_mode: host` is needed because Docker's bridge network does not pass
LAN broadcasts into a container. The listener can share a node with an agent.

## Running without Docker

```sh
pip install '.[listener]'
docmon-listener
```
