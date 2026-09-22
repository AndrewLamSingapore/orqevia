FROM python:3.12-slim
ARG PRIME_RUNTIME_REVISION=UNKNOWN
LABEL org.opencontainers.image.revision=$PRIME_RUNTIME_REVISION

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY config ./config
COPY clients/pwa/index.html clients/pwa/app.mjs clients/pwa/core.mjs clients/pwa/storage.mjs clients/pwa/style.css clients/pwa/sw.js clients/pwa/voice.mjs clients/pwa/manifest.webmanifest ./app/pwa_static/
COPY clients/pwa/icons ./app/pwa_static/icons

EXPOSE 8000

CMD ["uvicorn", "app.production_entry:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers"]
