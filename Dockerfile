# Two stages: the first one builds the virtual environment (it needs `uv` and
# compilers' worth of tooling), the second one is a small image that only
# carries the finished environment. The same image runs the API and the worker;
# they differ only in the command.

FROM python:3.12-slim AS build

# A pinned `uv`, so the same Dockerfile builds the same thing next year.
COPY --from=ghcr.io/astral-sh/uv:0.12.15 /uv /uvx /bin/

# Use the Python of this image (never download another), and precompile.
ENV UV_PYTHON_DOWNLOADS=never UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

WORKDIR /app
# Dependencies first, so this layer is cached until pyproject/uv.lock change.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project --no-editable

COPY src ./src
RUN uv sync --frozen --no-dev --no-editable


FROM python:3.12-slim

ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1

# The service does not need root, so it does not get it.
RUN useradd --system --uid 10001 --no-create-home app

WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

USER app
EXPOSE 8001

ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "tinyurl_py.main:app", "--host", "0.0.0.0", "--port", "8001"]
