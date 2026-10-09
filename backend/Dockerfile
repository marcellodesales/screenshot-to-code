# Docker CLI + compose/buildx plugins for the stack generator ("Build app"),
# which drives the host daemon through the mounted socket.
FROM docker:29.7.2-cli AS docker-cli

FROM python:3.12.3-slim-bookworm

ENV POETRY_VERSION 1.8.0

# git: per-run version history (data/runs/<run-id>).
# libatomic1: required by the node runtime pyright downloads.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git libatomic1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/docker
COPY --from=docker-cli /usr/local/libexec/docker/cli-plugins /usr/local/libexec/docker/cli-plugins

# Install system dependencies
RUN pip install "poetry==$POETRY_VERSION"

# Set work directory
WORKDIR /app

# Copy only requirements to cache them in docker layer
COPY poetry.lock pyproject.toml /app/

# Disable the creation of virtual environments
RUN poetry config virtualenvs.create false

# Install dependencies
RUN poetry install

# Install Chromium and Linux libraries needed by Playwright screenshot previews.
RUN playwright install --with-deps chromium

# Copy the current directory contents into the container at /app
COPY ./ /app/
