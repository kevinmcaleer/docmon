# syntax=docker/dockerfile:1
# Build from the repo root:  docker build -f agent/Dockerfile -t docmon-agent .
FROM python:3.12-slim

# Provenance labels for images built outside CI. CI overrides these with
# docker/metadata-action; pass them by hand with e.g.
#   --build-arg VCS_REF=$(git rev-parse HEAD) --build-arg BUILD_DATE=$(date -u +%FT%TZ)
ARG VCS_REF=""
ARG BUILD_DATE=""
ARG VERSION="0.1.0"
LABEL org.opencontainers.image.title="docmon-agent" \
      org.opencontainers.image.description="Broadcasts this node's Docker containers over UDP" \
      org.opencontainers.image.source="https://github.com/kevinmcaleer/docmon" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.version="${VERSION}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /src
COPY pyproject.toml README.md ./
COPY schema ./schema
COPY agent ./agent
RUN pip install ".[agent]" && rm -rf /src

WORKDIR /
# Runs as root only so it can read the mounted Docker socket; it never writes to it.
ENTRYPOINT ["docmon-agent"]
