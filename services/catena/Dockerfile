# The model layer. Dependencies come from the lockfile only — a build that
# resolves versions at image-build time makes "the same commit" mean two
# different stacks (SHARED §1).
FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.11.6 /uv /usr/local/bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

# Manifest and lock first, so the dependency layer caches independently of
# source. `--no-install-project` is what keeps that separation real.
COPY services/catena/pyproject.toml services/catena/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Source and the generated contract together, because both are packaged into
# the wheel. The stubs are committed rather than generated here (ADR-0022): the
# image needs no `buf` and the build reaches no network beyond the base image,
# which is what lets `docker compose up` work on a clean clone now that catena
# is part of the default `up`.
COPY services/catena/src ./src
COPY services/catena/gen ./gen

# `--no-editable` so the package lands in site-packages rather than as a link
# back to /app/src, which the runtime stage does not carry.
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.12-slim
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

# Weights and staged text are mounted, never baked in (ADR-0014, SHARED §1).
ENV CATENA_MODELS_DIR=/models
RUN useradd --create-home --uid 1001 catena
USER catena
ENTRYPOINT ["catena"]
CMD ["version"]
