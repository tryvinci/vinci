# Vinci OSS self-host container (Python 3.12 + ffmpeg). Build context: apps/vinci-oss root.
FROM python:3.12.11-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml Makefile ./
COPY packages ./packages
COPY skills ./skills
COPY apps/daemon ./apps/daemon
COPY deploy/cloudflare/container/requirements-selfhost.txt ./requirements-selfhost.txt

RUN python -m pip install --no-cache-dir "pip==25.0.1" \
    && python -m pip install --no-cache-dir -r requirements-selfhost.txt \
    && python -m pip install --no-cache-dir \
        -e packages/protocol \
        -e packages/core \
        -e packages/storage \
        -e packages/provider-sdk \
        -e packages/skills \
        -e packages/runtime \
        -e packages/mcp \
        -e packages/media \
        -e packages/index \
        -e packages/provider-google \
        -e packages/provider-openai \
        -e packages/provider-wavespeed \
        -e packages/provider-fal \
        -e packages/provider-elevenlabs \
        -e packages/provider-cloudflare \
        -e packages/provider-higgsfield \
        -e packages/provider-magnific \
        -e packages/harness \
        -e apps/daemon

RUN useradd -m -u 10001 vinci
ENV VINCI_HOME=/data/.vinci \
    VINCI_DAEMON_HOST=0.0.0.0 \
    VINCI_DAEMON_PORT=8080 \
    VINCI_CAS_BACKEND=r2 \
    VINCI_SELFHOST=1 \
    PYTHONUNBUFFERED=1

RUN mkdir -p /data/.vinci && chown -R vinci:vinci /data
USER vinci
WORKDIR /data

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz')" || exit 1

CMD ["vinci-selfhost"]
