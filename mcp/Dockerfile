# syntax=docker/dockerfile:1
# Build from the repo root:  docker build -f mcp/Dockerfile -t docmon-mcp .

# cffi (pulled in by the MCP SDK's crypto dependency) has no linux/arm/v7
# wheel, so wheels are built in a stage that has a compiler.
FROM python:3.12-slim AS build
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libc6-dev libffi-dev \
    && rm -rf /var/lib/apt/lists/*
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /src
COPY pyproject.toml README.md ./
COPY schema ./schema
COPY mcp ./mcp
RUN pip wheel --wheel-dir /wheels ".[mcp]"

FROM python:3.12-slim

# Provenance labels for images built outside CI. CI overrides these with
# docker/metadata-action; pass them by hand with e.g.
#   --build-arg VCS_REF=$(git rev-parse HEAD) --build-arg BUILD_DATE=$(date -u +%FT%TZ)
ARG VCS_REF=""
ARG BUILD_DATE=""
ARG VERSION="0.1.0"
LABEL org.opencontainers.image.title="docmon-mcp" \
      org.opencontainers.image.description="MCP server for what runs where on a docmon cluster, and where each image came from" \
      org.opencontainers.image.source="https://github.com/kevinmcaleer/docmon" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.version="${VERSION}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DOCMON_MCP_TRANSPORT=http

RUN --mount=type=bind,from=build,source=/wheels,target=/wheels \
    pip install --no-index --find-links=/wheels docmon[mcp] \
    && useradd --system --uid 10001 docmon

USER docmon
EXPOSE 8081
HEALTHCHECK --interval=60s --timeout=5s \
    CMD python -c "import urllib.request,os; urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.environ.get('DOCMON_MCP_PORT', '8081'))"
ENTRYPOINT ["docmon-mcp"]
