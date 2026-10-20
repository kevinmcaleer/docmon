# docmon MCP server

Lets Claude and other MCP clients ask what is running where on the cluster,
and where each image came from. It reads the
[listener's JSON API](../listener/README.md#json-api), so it needs a listener
running somewhere; it does not listen for broadcasts itself.

## Tools

| Tool | Answers |
| --- | --- |
| `list_nodes()` | Which nodes exist, and whether each is online, stale or gone |
| `list_containers(node?, image?)` | What runs on a node (or everywhere): status, uptime, image, compose project, repo and commit |
| `find_container(name)` | Where a container runs. Exact name matches first, otherwise any name containing `name` |
| `get_image_provenance(container? \| image?, node?)` | Which repo and commit an image was built from, with a commit URL, build time, version and digest |

So "where is grafana running and what repo was it built from?" comes back as
the node, its status, the container status, the repo URL, the commit and a
link to that commit.

### How provenance is worked out

1. The image's own OCI labels, as reported by the agent:
   `org.opencontainers.image.source`, `.revision`, `.created`, `.version`.
   `source` + `revision` become a commit URL (GitHub, GitLab, Bitbucket, and
   GitHub-style paths for anything else, which covers Gitea and Forgejo).
2. If the image has no `source` label, the server asks the image's registry
   (GHCR, Docker Hub, or any OCI registry) for the labels and annotations of
   the exact digest that is running. This is anonymous, so it only works for
   public images; turn it off with `DOCMON_REGISTRY_LOOKUP=false`.
3. If that finds nothing, the answer says plainly that provenance is unknown
   (`"known": false`) and gives the registry, repository, tag, digest and a
   link to the image's registry page. For GHCR images it also offers a
   `guessed_source` from the image name, marked as a guess.

`known` is `true` when both repo and commit are known, `"partial"` when only
the repo is, and `false` otherwise. `labels_from` says whether the labels came
from the image, the registry, or both.

To make your own images answer fully, build them with the labels set; see
[Image provenance labels](../README.md#image-provenance-labels).

## Run it next to the listener

```sh
docker compose -f examples/compose/mcp.yaml up -d
```

This serves MCP over streamable HTTP at `http://<that-node>:8081/mcp`, and
talks to the listener at `http://127.0.0.1:8080`. Images are published for
`linux/arm64` and `linux/arm/v7` at `ghcr.io/kevinmcaleer/docmon-mcp`.

The endpoint has no authentication; anyone on the LAN who can reach it can
read the container list (which the listener's web page shows anyway). Set
`DOCMON_MCP_ALLOWED_HOSTS` to reject requests addressed to other host names,
which guards against DNS rebinding from a browser.

## Connect a client

**Claude Code**, over HTTP:

```sh
claude mcp add --transport http docmon http://pi-1:8081/mcp
```

**Claude Desktop** and other clients that start a local server over stdio,
using the image (no Python needed):

```json
{
  "mcpServers": {
    "docmon": {
      "command": "docker",
      "args": [
        "run", "-i", "--rm",
        "-e", "DOCMON_LISTENER_URL=http://pi-1:8080",
        "ghcr.io/kevinmcaleer/docmon-mcp:latest", "--transport", "stdio"
      ]
    }
  }
}
```

or with docmon installed (`pip install 'docmon[mcp] @ git+https://github.com/kevinmcaleer/docmon'`):

```json
{
  "mcpServers": {
    "docmon": {
      "command": "docmon-mcp",
      "env": {"DOCMON_LISTENER_URL": "http://pi-1:8080"}
    }
  }
}
```

**VS Code** (`.vscode/mcp.json`):

```json
{"servers": {"docmon": {"type": "http", "url": "http://pi-1:8081/mcp"}}}
```

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `DOCMON_LISTENER_URL` | `http://127.0.0.1:8080` | Listener to read from |
| `DOCMON_MCP_TRANSPORT` | `stdio` (`http` in the image) | `stdio` or `http` (streamable HTTP); `--transport` overrides |
| `DOCMON_MCP_HOST` | `0.0.0.0` | Address for the HTTP transport |
| `DOCMON_MCP_PORT` | `8081` | Port for the HTTP transport; the endpoint is `/mcp` |
| `DOCMON_MCP_ALLOWED_HOSTS` | empty (any) | Comma-separated `Host` headers to accept, e.g. `pi-1:*,192.168.1.10:*` |
| `DOCMON_REGISTRY_LOOKUP` | `true` | Ask the registry for labels when the image has none |
| `DOCMON_PLATFORM` | `linux/arm64` | Which platform's labels to read from a multi-arch image |
| `DOCMON_TIMEOUT` | `10` | Seconds to wait for the listener or a registry |
| `DOCMON_LOG_LEVEL` | `INFO` | Logs go to stderr |

## Running without Docker

```sh
pip install '.[mcp]'
docmon-mcp --transport http --listener http://pi-1:8080
```
