# Base Image: Lightweight Python 3.10
# We use 'slim' to minimize attack surface and image size
FROM python:3.10-slim

# Meta Information
LABEL maintainer="Quant OS Architect"
LABEL version="3.1"
LABEL description="Tactical Command System"

# ==============================================================================
# 1. ENVIRONMENT CONFIGURATION
# ==============================================================================
# Prevents Python from writing pyc files to disc
ENV PYTHONDONTWRITEBYTECODE=1
# Prevents Python from buffering stdout and stderr (Real-time logging)
ENV PYTHONUNBUFFERED=1
# The Timezone Law: Internal System Time is ALWAYS UTC
ENV TZ=UTC

# ==============================================================================
# 2. SYSTEM DEPENDENCIES
# ==============================================================================
# Install GCC (required for compiling some math libraries like numpy on Linux)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# ==============================================================================
# 3. APPLICATION SETUP
# ==============================================================================
WORKDIR /app

# Copy requirements first to leverage Docker Layer Caching
# (If you change code but not requirements, this step is skipped = faster builds)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the entire project into the container
COPY . .

# Create directory mount points for persistence (The Vault & Logs)
RUN mkdir -p /app/data /app/logs

# ==============================================================================
# 4. RUNTIME CONFIGURATION
# ==============================================================================
# Expose the Dash UI port
EXPOSE 8050

# Default entry point (Overridden by docker-compose for the Sentinel)
CMD ["python", "app.py"]