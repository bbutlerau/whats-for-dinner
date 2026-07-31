# A single-stage image is plenty here: the app is pure Python with no build step,
# so there's nothing to compile and discard.
FROM python:3.12-slim

# Copy uv in from its official image rather than installing it with pip — it's a
# static binary, so this is both faster and smaller than a pip install.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# Dependencies are installed before the source is copied so that editing code
# doesn't invalidate the (slow) dependency layer on every rebuild.
#
# The install comes from uv.lock via --frozen, so the image gets exactly the
# versions the test suite ran against rather than whatever happens to resolve on
# build day. --no-install-project skips the app itself at this stage: it isn't
# copied yet, and installing it here would defeat the layer caching.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY app ./app

# Now that the source is present, install the project itself into the same
# environment. This layer is cheap because the dependencies are already there.
RUN uv sync --frozen --no-dev

# uv installs into .venv rather than the system Python, so put it on PATH and
# the CMD below can call uvicorn directly.
ENV PATH="/app/.venv/bin:$PATH"

# The database lives on a mounted volume, not in the image.
ENV DATABASE_URL=sqlite:////data/mealplanner.db
VOLUME ["/data"]

EXPOSE 7007

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7007"]
