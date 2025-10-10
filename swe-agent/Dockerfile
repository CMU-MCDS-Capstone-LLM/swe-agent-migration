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
    && rm -rf /var/lib/apt/lists/*
# Copy your existing swe-agent code
COPY . .

# Install Python dependencies including dev dependencies
RUN pip install -e ".[dev]"

# Create required directories (tools already exists from COPY . .)
RUN mkdir -p /app/trajectories

# Set working directory to app directory
WORKDIR /app

# The command will be overridden by docker-compose
CMD ["python", "sweagent/run/run.py", "run"]

