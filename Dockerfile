# =============================================================================
# Dockerfile — Content Automation API
# =============================================================================
#
# BUILD & RUN
#   docker build -t content-automation .
#   docker run -p 8000:8000 --env-file backend/.env content-automation
#
# WHY python:3.13-slim AND NOT python:3.13
# -----------------------------------------
# The full Python image includes compilers, docs, and dev tools (~900 MB).
# The slim variant strips all of that down to ~50 MB. Our app has no
# C extension build steps at runtime, so slim is sufficient.
#
# LAYER CACHING — THE MOST IMPORTANT DOCKERFILE OPTIMIZATION
# ----------------------------------------------------------
# Docker caches each RUN/COPY instruction as a layer. If a layer's inputs
# haven't changed, Docker reuses the cached result instead of re-running it.
#
# The order here is deliberate:
#   1. COPY requirements.txt  ← only changes when dependencies change
#   2. RUN pip install        ← cached as long as requirements.txt is unchanged
#   3. COPY backend/          ← changes every time code changes
#
# If we did COPY backend/ FIRST, every code change would invalidate the pip
# install layer and reinstall all dependencies from scratch — very slow.
# With this order, a code-only change skips step 2 entirely.
#
# WHY --no-cache-dir
# ------------------
# pip normally caches downloaded wheels in ~/.cache/pip. In a Docker build,
# that cache is thrown away when the container exits anyway. Skipping it
# reduces the final image size.
#
# WHY libfreetype6-dev
# --------------------
# Pillow needs FreeType to render TrueType fonts (.ttf files).
# The slim base image doesn't include it. Without this, _load_font() in
# compositor.py would fail to load Inter and fall back to PIL's bitmap font.
# =============================================================================

FROM python:3.13-slim

WORKDIR /app

# System dependencies for Pillow TrueType font rendering.
# --no-install-recommends skips optional packages → smaller image.
# Clean up apt lists after install to avoid caching them in the layer.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libfreetype6-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy and install dependencies BEFORE copying application code.
# This layer is cached until requirements.txt changes — see note above.
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the full backend directory (code, assets, fonts).
COPY backend/ ./backend/

# Pre-create the output directory for generated carousel images.
# Without this, the first POST /generate would create it at runtime,
# which can fail if the process doesn't have write permissions.
RUN mkdir -p /app/carousels

# Set working directory to backend/ so uvicorn finds app.main correctly.
WORKDIR /app/backend

EXPOSE 8000

# 0.0.0.0 binds to all network interfaces inside the container —
# required for Docker port mapping (-p 8000:8000) to work.
# Without it, uvicorn would only listen on localhost inside the container
# and be unreachable from the host machine.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
