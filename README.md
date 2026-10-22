# docmon

Find out which Docker containers are running on which node of a small
cluster (for example a stack of Raspberry Pis on one LAN).

Each node runs a tiny **agent** that reads its local Docker socket and, about
once a minute, broadcasts a JSON list of its containers over UDP. A
**listener** on any node collects those broadcasts into one view of what is
running where, including the repo and commit each image was built from. An
optional **MCP server** lets Claude answer questions like "where is grafana
running and which commit was it built from?". Your existing containers need
no changes.

| Part | Folder | Status |
| --- | --- | --- |
| Node agent | [`agent/`](agent/) | ready |
| Shared message schema | [`schema/`](schema/) | ready |
| Listener (web page + JSON API) | [`listener/`](listener/) | ready |
| MCP server (for Claude and other MCP clients) | [`mcp/`](mcp/) | ready |

## Quick start: run the agent on each node

Copy [`examples/compose/agent.yaml`](examples/compose/agent.yaml) to each Pi
and start it:

```sh
docker compose -f agent.yaml up -d
```

Images are published for `linux/arm64` and `linux/arm/v7` at
`ghcr.io/kevinmcaleer/docmon-agent`.

Check the broadcasts are arriving from any machine on the LAN:

```sh
nc -ul 50505                         # prints one JSON message per beat
sudo tcpdump -A -i any udp port 50505
```

Or see what a node would send without sending it:

```sh
docker compose -f agent.yaml run --rm docmon-agent --once --dry-run
```

## Quick start: run the listener on one node

Copy [`examples/compose/listener.yaml`](examples/compose/listener.yaml) to any
one node (it can also run an agent), start it, and open
`http://<that-node>:8080`:

```sh
docker compose -f listener.yaml up -d
```

Every node's containers appear within about a minute. A node whose agent
stops is marked stale after about three minutes. The JSON API and the
listener's settings are described in [listener/README.md](listener/README.md).
On a Mac with Docker Desktop, use
[`examples/compose/listener-mac.yaml`](examples/compose/listener-mac.yaml)
instead (see [Running on a Mac](listener/README.md#running-on-a-mac-docker-desktop)).
Images are published for the same platforms at
`ghcr.io/kevinmcaleer/docmon-listener`.

## Quick start: ask Claude about the cluster

Run the MCP server next to the listener with
[`examples/compose/mcp.yaml`](examples/compose/mcp.yaml), then add it to
Claude Code:

```sh
docker compose -f mcp.yaml up -d
claude mcp add --transport http docmon http://<that-node>:8081/mcp
```

Its tools, how it works out provenance, and configs for Claude Desktop and
other clients are in [mcp/README.md](mcp/README.md). Images are published for
the same platforms at `ghcr.io/kevinmcaleer/docmon-mcp`.

## Agent configuration

All settings are environment variables on the agent container.

| Variable | Default | Meaning |
| --- | --- | --- |
| `DOCMON_PORT` | `50505` | UDP port to broadcast to |
| `DOCMON_BROADCAST_ADDR` | `255.255.255.255` | Destination address; set a subnet broadcast (e.g. `192.168.1.255`) or a listener's IP if needed |
| `DOCMON_INTERVAL` | `60` | Seconds between beats |
| `DOCMON_JITTER` | `5` | Up to this many extra random seconds per beat, so nodes don't send in lockstep |
| `DOCMON_MAX_DATAGRAM` | `1400` | Largest datagram in bytes; bigger beats are split |
| `DOCMON_INCLUDE_STOPPED` | `false` | Also report stopped containers |
| `DOCMON_NODE_NAME` | host's hostname | Name to report for this node |
| `DOCMON_NODE_IP` | auto-detected | IP to report for this node |
| `DOCMON_LOG_LEVEL` | `INFO` | `DEBUG` logs every beat |

The message format is described in [docs/message-format.md](docs/message-format.md).

### A note on the Docker socket

The socket is mounted `:ro`, which stops the file being replaced but does not
limit the Docker API: anything that can talk to the socket can control
Docker. The agent only makes read calls (`containers`, `inspect`). If you want
that enforced, put a socket proxy such as
[tecnativa/docker-socket-proxy](https://github.com/Tecnativa/docker-socket-proxy)
with only `CONTAINERS=1` and `IMAGES=1` in front of it and set
`DOCKER_HOST=tcp://<proxy>:2375` on the agent.

## Image provenance labels

docmon reports these OCI labels for every container, when the image has them:

| Label | Reported as |
| --- | --- |
| `org.opencontainers.image.source` | `oci.source` (repo URL) |
| `org.opencontainers.image.revision` | `oci.revision` (commit SHA) |
| `org.opencontainers.image.created` | `oci.created` (build time) |
| `org.opencontainers.image.version` | `oci.version` |

**Images built in GitHub Actions.** Call the reusable workflow from any of
your repos and the labels are set for you:

```yaml
# .github/workflows/image.yml in another repo
on:
  push:
    branches: [main]
    tags: ["v*"]
jobs:
  image:
    uses: kevinmcaleer/docmon/.github/workflows/build-image.yml@main
    permissions:
      contents: read
      packages: write
    with:
      image: ghcr.io/${{ github.repository }}
      # context: .
      # dockerfile: Dockerfile
      # platforms: linux/arm64,linux/arm/v7
```

**Images built by hand.** Add the labels in the Dockerfile:

```dockerfile
ARG VCS_REF
ARG BUILD_DATE
LABEL org.opencontainers.image.source="https://github.com/you/yourapp" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.created="${BUILD_DATE}"
```

```sh
docker build --build-arg VCS_REF=$(git rev-parse HEAD) \
             --build-arg BUILD_DATE=$(date -u +%FT%TZ) -t yourapp .
```

or in compose with `build.labels`, as in
[`examples/compose/build-labels.yaml`](examples/compose/build-labels.yaml).
Check the result with:

```sh
docker inspect --format '{{json .Config.Labels}}' yourapp
```

## Development

```sh
python -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
ruff check . && ruff format --check .
pytest
docker build -f agent/Dockerfile -t docmon-agent .
docker build -f listener/Dockerfile -t docmon-listener .
docker build -f mcp/Dockerfile -t docmon-mcp .
```

CI runs lint and tests on every push and pull request
([`ci.yml`](.github/workflows/ci.yml)). Pushes to `main` and `v*` tags
publish the multi-arch agent, listener and MCP images to GHCR
([`publish.yml`](.github/workflows/publish.yml), which calls
[`build-image.yml`](.github/workflows/build-image.yml)).
