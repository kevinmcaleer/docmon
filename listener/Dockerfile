# syntax=docker/dockerfile:1
# Build from the repo root:  docker build -f listener/Dockerfile -t docmon-listener .
FROM python:3.12-slim

# Provenance labels for images built outside CI. CI overrides these with
# docker/metadata-action; pass them by hand with e.g.
#   --build-arg VCS_REF=$(git rev-parse HEAD) --build-arg BUILD_DATE=$(date -u +%FT%TZ)
ARG VCS_REF=""
ARG BUILD_DATE=""
ARG VERSION="0.1.0"
LABEL org.opencontainers.image.title="docmon-listener" \
      org.opencontainers.image.description="Collects docmon broadcasts and shows what runs where" \
      org.opencontainers.image.source="https://github.com/kevinmcaleer/docmon" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.version="${VERSION}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DOCMON_DB=/data/docmon.sqlite

WORKDIR /src
COPY pyproject.toml README.md ./
COPY schema ./schema
COPY listener ./listener
RUN pip install ".[listener]" && rm -rf /src \
    && useradd --system --uid 10001 docmon && mkdir /data && chown docmon /data

WORKDIR /
USER docmon
VOLUME /data
EXPOSE 8080 50505/udp
HEALTHCHECK --interval=60s --timeout=5s \
    CMD python -c "import urllib.request,os; urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.environ.get('DOCMON_HTTP_PORT', '8080'))"
ENTRYPOINT ["docmon-listener"]
