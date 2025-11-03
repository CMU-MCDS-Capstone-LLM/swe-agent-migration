#!/bin/bash
# SWE-agent script for Docker container execution

echo "Starting SWE-agent in Docker container..."

# Set up paths for container execution
TOOLS_DIR="/app/tools"  # Tools directory inside container
REPO_NAME="${REPO_NAME}"

# Clean up temporary files from previous runs (but keep tool bundles)
echo "Cleaning up temporary files..."
find "$TOOLS_DIR" -name "*.tmp" -delete 2>/dev/null || true
find "$TOOLS_DIR" -name "*.log" -delete 2>/dev/null || true
echo "Temporary files cleanup complete."

# Verify the repository exists
if [ -z "$REPO_NAME" ]; then
    echo "ERROR: REPO_NAME environment variable not set!"
        exit 1
fi

# SWE-agent expects the repo at /{repo_name} via symlink
REPO_PATH="/$REPO_NAME"

# Check if symlink exists and points to valid directory
if [ -L "$REPO_PATH" ]; then
    TARGET=$(readlink -f "$REPO_PATH")
    if [ ! -d "$TARGET" ]; then
        echo "ERROR: Symlink target directory $TARGET does not exist!"
        echo "Contents of /workspace:"
        ls -la /workspace || true
        exit 1
    fi
elif [ ! -d "$REPO_PATH" ]; then
    echo "ERROR: Repository directory $REPO_PATH not found!"
    echo "Contents of root:"
    ls -la / | head -20 || true
    exit 1
fi
    
echo "Processing repository: $REPO_NAME"
echo "Repository path: $REPO_PATH"

# Run SWE-agent with problem statement from environment variable
echo "Running SWE-agent..."

# Set output directory based on repo name
OUTPUT_BASE="${SWE_AGENT_OUTPUT_DIR:-}"
if [ -n "$OUTPUT_BASE" ] && [ -n "$REPO_NAME" ]; then
    OUTPUT_DIR="$OUTPUT_BASE/$REPO_NAME"
    mkdir -p "$OUTPUT_DIR"
    OUTPUT_ARG="--output_dir=$OUTPUT_DIR"
    echo "Using custom output directory: $OUTPUT_DIR"
fi

# We're already in /app (coding-agent directory) so no need to cd
python sweagent/run/run.py run \
  --config=./config/code_migration.yaml \
  --env.deployment.type=local \
  --env.repo.type=preexisting \
  --env.repo.repo_name="$REPO_NAME" \
  --problem_statement.type=text \
  --problem_statement.text="${PROBLEM_STATEMENT:-Code migration task for $REPO_NAME. Container name: repo-$REPO_NAME}" \
  $OUTPUT_ARG

echo "SWE-agent completed"