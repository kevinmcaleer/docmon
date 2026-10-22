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

### Changing the web port

If something else on the node already uses 8080, the listener exits with
`address already in use`. The compose files read `DOCMON_HTTP_PORT` from your
shell, so pick another port when starting it:

```sh
DOCMON_HTTP_PORT=8090 docker compose -f listener.yaml up -d
sudo ss -ltnp | grep ':8080'   # shows what is holding 8080
```

Start `mcp.yaml` with the same variable so the MCP server can find the
listener. To make the change permanent, put `DOCMON_HTTP_PORT=8090` in a
`.env` file next to the compose file.

`network_mode: host` is needed because Docker's bridge network does not pass
LAN broadcasts into a container. The listener can share a node with an agent.

## Running on a Mac (Docker Desktop)

On Docker Desktop, `network_mode: host` refers to Docker's Linux VM rather
than your Mac, so with `listener.yaml` the listener runs but
`http://localhost:8080` is refused. Use
[`examples/compose/listener-mac.yaml`](../examples/compose/listener-mac.yaml)
instead. It publishes `8080/tcp` and `50505/udp`:

```sh
docker compose -f listener-mac.yaml up -d
open http://localhost:8080
```

Broadcasts have to cross Docker Desktop's port forwarding to reach the
container, and that is less reliable for broadcast than for normal traffic.
To check, run with `DOCMON_LOG_LEVEL: DEBUG` and watch for `beat from` lines
in `docker logs -f docmon-listener`, or wait a minute and look at
`http://localhost:8080/api/nodes`. If nothing arrives, you can either:

- enable host networking instead: Docker Desktop 4.34 or later, under Settings →
  Resources → Network → **Enable host networking**. Then `listener.yaml`
  works as on a Pi.
- or have the agents send straight to the Mac by setting
  `DOCMON_BROADCAST_ADDR` to the Mac's LAN IP. Note that the agents then stop
  broadcasting, so a listener on a Pi would no longer hear them.

Also check the macOS firewall isn't blocking incoming connections for Docker.

## Running without Docker

```sh
pip install '.[listener]'
docmon-listener
```
