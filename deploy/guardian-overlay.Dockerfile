# Local, dependency-preserving release on a separately qualified production image.
# BASE_IMAGE must resolve locally to the recorded immutable image identity.
# Build with --network=none --pull=false; this does not fetch new dependencies.
ARG BASE_IMAGE
FROM ${BASE_IMAGE}
ARG ORQEVIA_RUNTIME_REVISION
ARG ORQEVIA_BASE_IMAGE_ID
COPY app /app/app
ENV ORQEVIA_RUNTIME_REVISION=${ORQEVIA_RUNTIME_REVISION}
LABEL org.opencontainers.image.revision=${ORQEVIA_RUNTIME_REVISION} \
      org.orqevia.release.base-image=${ORQEVIA_BASE_IMAGE_ID} \
      org.orqevia.release.scope="backend-app-overlay-existing-dependencies"
