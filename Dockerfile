FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
RUN mkdir -p /run/prime-tls

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY config ./config
# The deterministic architecture lookup reads these frozen records at /app/governance.
# Keep the image scope narrow; other governance files are not runtime inputs.
COPY governance/golden-gen1-manifest.json governance/golden-gen2-manifest.json ./governance/
# Only the verifier's public key metadata is needed in the runtime image.
COPY governance/agent-cert-verifier-azure-pins.json ./governance/agent-cert-verifier-azure-pins.json
COPY clients/pwa/index.html clients/pwa/recovery.js clients/pwa/release.mjs clients/pwa/app.mjs clients/pwa/core.mjs clients/pwa/storage.mjs clients/pwa/style.css clients/pwa/sw.js clients/pwa/voice.mjs clients/pwa/manifest.webmanifest ./app/pwa_static/
COPY clients/pwa/icons ./app/pwa_static/icons

# Keep revision metadata after dependency installation so a new source commit
# does not invalidate the expensive, reproducible requirements layer.
ARG PRIME_RUNTIME_REVISION=UNKNOWN
ENV PRIME_RUNTIME_REVISION=$PRIME_RUNTIME_REVISION
LABEL org.opencontainers.image.revision=$PRIME_RUNTIME_REVISION

EXPOSE 8000

CMD ["uvicorn", "app.production_entry:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers"]
