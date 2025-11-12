#!/bin/bash
# SWE-agent script for Docker container execution

echo "Starting SWE-agent in Docker container..."

# Set up paths for container execution
WORKSPACE_DIR="${WORKSPACE_DIR:-/data/repos}"
TOOLS_DIR="/app/tools"  # Tools directory inside container
REPO_NAME="${REPO_NAME}"

echo "Cleaning up temporary files..."
find "$TOOLS_DIR" -name "*.tmp" -delete 2>/dev/null || true
find "$TOOLS_DIR" -name "*.log" -delete 2>/dev/null || true
echo "Temporary files cleanup complete."

# Verify the repository exists
if [ -z "$REPO_NAME" ]; then
    echo "ERROR: REPO_NAME environment variable not set!"
        exit 1
    fi
    
if [ ! -d "$WORKSPACE_DIR/$REPO_NAME" ]; then
    echo "ERROR: Repository directory $WORKSPACE_DIR/$REPO_NAME not found!"
        exit 1
    fi

ln -sf "$WORKSPACE_DIR/$REPO_NAME" "/$REPO_NAME"

git config --global --add safe.directory "$WORKSPACE_DIR/$REPO_NAME"
git config --global --add safe.directory "/$REPO_NAME"
    
echo "Processing repository: $REPO_NAME"
echo "Repository path: $WORKSPACE_DIR/$REPO_NAME"

echo "Running SWE-agent..."

# Use OUTPUT_DIR if provided, otherwise use default
OUTPUT_DIR="${OUTPUT_DIR:-/app/trajectories}"

echo "Output directory: $OUTPUT_DIR"

python sweagent/run/run.py run \
  --config=./config/code_migration.yaml \
  --env.deployment.type=local \
  --env.repo.type=preexisting \
  --env.repo.repo_name="$REPO_NAME" \
  --problem_statement.type=text \
  --problem_statement.text="${PROBLEM_STATEMENT:-Code migration task for $REPO_NAME. Container name: repo-$REPO_NAME}" \
  --output_dir "$OUTPUT_DIR"

echo "SWE-agent completed"