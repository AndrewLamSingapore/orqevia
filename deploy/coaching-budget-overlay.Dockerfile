# Replace the existing producer role only. All dependencies and data stay put.
# Build against the recorded local coaching image, --network=none --pull=false.
ARG BASE_IMAGE
FROM ${BASE_IMAGE}
ARG ORQEVIA_RUNTIME_REVISION
ARG ORQEVIA_BASE_IMAGE_ID
COPY app/agent_coaching.py /app/app/agent_coaching.py
COPY app/home_eco.py /app/app/home_eco.py
LABEL org.opencontainers.image.revision=${ORQEVIA_RUNTIME_REVISION} \
      org.orqevia.release.base-image=${ORQEVIA_BASE_IMAGE_ID} \
      org.orqevia.release.scope="existing-coaching-producer-task-budgets"
