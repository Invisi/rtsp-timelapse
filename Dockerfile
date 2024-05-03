# syntax=docker/dockerfile:1

ARG PYTHON_VERSION=3.12.3
FROM python:${PYTHON_VERSION}-slim as base

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

ARG UID=1001
RUN adduser \
    --disabled-password \
    --gecos "" \
    --home "/nonexistent" \
    --shell "/sbin/nologin" \
    --no-create-home \
    --uid "${UID}" \
    abc

# cache dirs
ENV APT_CACHE=/var/cache/apt/archives/
ENV POETRY_CACHE_DIR=/tmp/pypoetry

# poetry
# https://python-poetry.org/docs/configuration/#using-environment-variables
ARG POETRY_VERSION="1.8.2"
# make poetry install to this location
ENV POETRY_HOME="/opt/poetry"
# create .venv in PYSETUP_PATH
ENV POETRY_VIRTUALENVS_IN_PROJECT=true
# skip interactive questions
ENV POETRY_NO_INTERACTION=1

ENV PATH="$POETRY_HOME/bin:$PATH"

RUN --mount=type=cache,target=$APT_CACHE \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        curl ffmpeg && \
    pip install -U pip && \
    apt-get clean

# install poetry - respects $POETRY_VERSION & $POETRY_HOME
RUN curl -sSL https://install.python-poetry.org/ | python
RUN poetry config virtualenvs.create false

WORKDIR /app
COPY pyproject.toml poetry.lock ./

# install runtime deps - uses $POETRY_VIRTUALENVS_IN_PROJECT internally
RUN --mount=type=cache,target=$POETRY_CACHE_DIR \
    poetry install --no-root --compile

# set up data volume
ENV DATA_PATH=/app/data
VOLUME /app/data
RUN mkdir /app/data

# fix permissions
RUN chown -R abc /app

# swap to user & copy code
USER abc
COPY . .

CMD python main.py
