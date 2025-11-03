FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
# Install build tools
RUN apt-get update && apt-get install -y \
    build-essential \
    gcc \
    rustc \
    cargo \
    pkg-config \
    libssl-dev \
    git \
    docker.io \
    && rm -rf /var/lib/apt/lists/*

# Copy the entire codebase first (needed for dynamic version reading)
COPY . .

# Install Python dependencies including dev dependencies
RUN pip install -e ".[dev]"

# Create required directories
RUN mkdir -p /app/tools /app/trajectories

# The code will be mounted as a volume at runtime, overriding the copied code
CMD ["python", "sweagent/run/run.py", "run"]

