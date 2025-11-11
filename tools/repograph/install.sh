#!/bin/bash
# Install script for repograph tool

# Make Python script executable
chmod +x tools/repograph/lib/repograph_tool.py

# Make shell script executable
chmod +x tools/repograph/bin/repograph_query

# Install requests if not already available (needed for HTTP client)
python3 -c "import requests" 2>/dev/null || pip install -q requests

echo "RepoGraph tool installed successfully"

