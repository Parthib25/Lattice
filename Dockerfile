# Use an official Python runtime as a parent image
FROM python:3.13-slim

# Set system environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    WORKSPACE_DIR=/app

# Set the working directory in the container
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and project metadata files first
COPY pyproject.toml README.md /app/
COPY lattice/ /app/lattice/

# Install uv and use it to sync application dependencies
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv
RUN uv sync --no-cache

# Ensure virtual environment binaries are in the path
ENV PATH="/app/.venv/bin:$PATH"

# Copy the rest of the static static template UI files
COPY static/ /app/static/
COPY .env /app/.env

# Expose the server port
EXPOSE 8000

# Run uvicorn server on container startup
CMD ["uv", "run", "uvicorn", "lattice.server:app", "--host", "0.0.0.0", "--port", "8000"]
