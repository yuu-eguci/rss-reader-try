# syntax=docker/dockerfile:1

FROM ghcr.io/astral-sh/uv:0.12.23@sha256:61d393e44e249f2e4b526b6c7ddcecce245946826e608e11c93ad4f5bba55b21 AS uv

FROM python:3.15-alpine@sha256:1afb480ba8d3b3b7a8439a84f2365ce5c75ac45a79cf07daa091b49235cbe27b AS base
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./

# Lint and tests: `docker build --target dev -t rss-reader-try:dev . && docker run --rm rss-reader-try:dev`
FROM base AS dev
RUN uv sync --locked --no-install-project
COPY src ./src
COPY tests ./tests
COPY examples ./examples
RUN uv sync --locked
CMD ["sh", "-c", "ruff check . && ruff format --check . && mypy && coverage run -m pytest && coverage report"]

FROM base AS build
RUN uv sync --locked --no-dev --no-install-project
COPY src ./src
RUN uv sync --locked --no-dev --no-editable

FROM python:3.15-alpine@sha256:1afb480ba8d3b3b7a8439a84f2365ce5c75ac45a79cf07daa091b49235cbe27b
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
RUN adduser -D -u 10001 app && install -d -o app -g app /data
COPY --from=build /opt/venv /opt/venv
WORKDIR /data
USER app
ENTRYPOINT ["rss-reader-try"]
CMD ["--help"]
