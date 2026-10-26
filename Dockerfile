FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
RUN mkdir -p /run/orqevia-tls
COPY requirements.pip-security.txt ./
RUN python -m pip install --no-cache-dir --no-deps --require-hashes --index-url https://pypi.org/simple -r requirements.pip-security.txt

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Install the reviewed upstream MBTI-in-Thoughts runtime wheel. Its research
# dependency declarations are removed because that pinned Torch/LangChain
# environment conflicts with ORQEVIA's production dependency closure.
COPY vendor/MBTI-in-Thoughts-1.0.0/mbti_in_thoughts-1.0.0-1orqevia-py3-none-any.whl /tmp/
RUN pip install --no-cache-dir --no-deps /tmp/mbti_in_thoughts-1.0.0-1orqevia-py3-none-any.whl \
    && rm /tmp/mbti_in_thoughts-1.0.0-1orqevia-py3-none-any.whl

COPY app ./app
COPY mbti_in_thoughts ./mbti_in_thoughts
COPY config ./config
# The deterministic architecture lookup reads the current golden record at /app/governance.
# Keep the image scope narrow; other governance files are not runtime inputs.
COPY governance/golden-gen4-manifest.json ./governance/
# Only the verifier's public key metadata is needed in the runtime image.
COPY governance/agent-cert-verifier-azure-pins.json ./governance/agent-cert-verifier-azure-pins.json
COPY clients/pwa/index.html clients/pwa/recovery.js clients/pwa/release.mjs clients/pwa/app.mjs clients/pwa/core.mjs clients/pwa/storage.mjs clients/pwa/style.css clients/pwa/sw.js clients/pwa/voice.mjs clients/pwa/manifest.webmanifest ./app/pwa_static/
COPY clients/pwa/reset.html clients/pwa/reset.mjs ./app/pwa_static/
COPY clients/pwa/dashboard.mjs clients/pwa/dashboard.css ./app/pwa_static/
COPY clients/pwa/projects.html clients/pwa/projects.css clients/pwa/projects.mjs ./app/pwa_static/
COPY clients/pwa/intelligence.mjs clients/pwa/integration-panels.mjs clients/pwa/intelligence.css clients/pwa/command-center.css ./app/pwa_static/
COPY clients/pwa/knowledge.mjs clients/pwa/knowledge.css clients/pwa/workspace-tools.mjs ./app/pwa_static/
COPY clients/pwa/command-map.mjs clients/pwa/command-map.css clients/pwa/agent-readiness.json clients/pwa/registry.json ./app/pwa_static/
COPY clients/pwa/vendor ./app/pwa_static/vendor
COPY clients/pwa/icons ./app/pwa_static/icons
COPY clients/public ./app/public_static
COPY clients/shared ./app/shared_static
COPY clients/pwa/sovereign.css clients/pwa/sovereign.mjs clients/pwa/operations.mjs ./app/pwa_static/
COPY clients/pwa/intelligence-capabilities.mjs ./app/pwa_static/

# Keep revision metadata after dependency installation so a new source commit
# does not invalidate the expensive, reproducible requirements layer.
ARG ORQEVIA_RUNTIME_REVISION=UNKNOWN
ENV ORQEVIA_RUNTIME_REVISION=$ORQEVIA_RUNTIME_REVISION
LABEL org.opencontainers.image.revision=$ORQEVIA_RUNTIME_REVISION

EXPOSE 8000

# Fatal-fault diagnostics contain frame locations, not locals or source values.
# No timer, signal injection, core dump or additional privilege is introduced.
CMD ["python", "-X", "faulthandler", "-m", "uvicorn", "app.production_entry:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers"]
