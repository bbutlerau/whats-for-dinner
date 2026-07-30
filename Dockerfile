# A single-stage image is plenty here: the app is pure Python with no build step,
# so there's nothing to compile and discard.
FROM python:3.12-slim

# Copy uv in from its official image rather than installing it with pip — it's a
# static binary, so this is both faster and smaller than a pip install.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_SYSTEM_PYTHON=1 \
    UV_COMPILE_BYTECODE=1

WORKDIR /app

# Dependencies are installed before the source is copied so that editing code
# doesn't invalidate the (slow) dependency layer on every rebuild.
COPY pyproject.toml README.md ./
RUN uv pip install --system \
        "fastapi>=0.115" \
        "uvicorn[standard]>=0.32" \
        "sqlmodel>=0.0.22" \
        "jinja2>=3.1" \
        "python-multipart>=0.0.17" \
        "pydantic-settings>=2.6" \
        "httpx>=0.27"

COPY app ./app

# The database lives on a mounted volume, not in the image.
ENV DATABASE_URL=sqlite:////data/mealplanner.db
VOLUME ["/data"]

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
