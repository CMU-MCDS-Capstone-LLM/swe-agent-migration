#!/bin/bash
# Script to start the worker agent and process repositories

echo "Worker starting..."

# Clean up SWE-agent tools from previous runs to avoid conflicts
echo "Cleaning up SWE-agent tools from previous runs..."
rm -rf /root/tools 2>/dev/null || true
mkdir -p /root/tools
echo "Tools cleanup complete."

# Clean up ONLY testing agent output artifacts (keep tests/ directory and testing_complete.flag!)
echo "Cleaning up testing agent output artifacts..."
find /workspace -type f -name "*.log" ! -path "*/tests/*" -delete 2>/dev/null || true
find /workspace -type f -name ".coverage" -delete 2>/dev/null || true
find /workspace -type f -name "coverage.xml" -delete 2>/dev/null || true
echo "Cleanup complete (kept tests/ directory and testing_complete.flag)."

# Check if we should process all repos or a specific one
# Note: Docker compose sets empty variables to "", not unset, so we check for both
if [ -z "$REPO_NAME" ] || [ "$REPO_NAME" = "" ]; then
    echo "No specific repo specified, reading all repos from repo_config.yaml"
    
    # Get list of all repositories from repo_config.yaml
    if [ ! -f "/app/repo_config.yaml" ]; then
        echo "ERROR: repo_config.yaml not found!"
        exit 1
    fi
    
    # Extract all repository names from the config
    REPO_NAMES=$(python3 -c "
import yaml
try:
    with open('/app/repo_config.yaml', 'r') as f:
        config = yaml.safe_load(f)
    if 'repositories' in config:
        for repo_name in config['repositories'].keys():
            print(repo_name)
except Exception as e:
    import sys
    print(f'Error reading repo_config.yaml: {e}', file=sys.stderr)
    sys.exit(1)
")
    
    if [ -z "$REPO_NAMES" ]; then
        echo "ERROR: No repositories found in repo_config.yaml"
        exit 1
    fi
    
    echo "Found repositories to process:"
    echo "$REPO_NAMES"
    echo ""
    
    # Wait for testing agent to complete all repositories
    echo "Waiting for testing agent to complete all repositories..."
    TIMEOUT=600  # 10 minutes
    ELAPSED=0
    
    # Convert REPO_NAMES to array
    readarray -t REPOS_ARRAY <<< "$REPO_NAMES"
    TOTAL_REPOS=${#REPOS_ARRAY[@]}
    
    while [ $ELAPSED -lt $TIMEOUT ]; do
        REPOS_READY=0
        
        for repo_name in "${REPOS_ARRAY[@]}"; do
            TESTING_COMPLETE_FLAG="/workspace/$repo_name/testing_complete.flag"
            if [ -f "$TESTING_COMPLETE_FLAG" ]; then
                REPOS_READY=$((REPOS_READY + 1))
            fi
        done
        
        if [ $REPOS_READY -eq $TOTAL_REPOS ]; then
            echo "All repositories are ready for processing ($REPOS_READY/$TOTAL_REPOS)"
            break
        fi
        
        echo "Waiting for testing agent to complete... ($REPOS_READY/$TOTAL_REPOS repos ready) (${ELAPSED}s/${TIMEOUT}s)"
        sleep 10
        ELAPSED=$((ELAPSED + 10))
    done
    
    if [ $ELAPSED -ge $TIMEOUT ]; then
        echo "ERROR: Timeout waiting for testing agent to complete"
        exit 1
    fi
    
    # Process each repository sequentially
    for repo_name in "${REPOS_ARRAY[@]}"; do
        echo "================================================"
        echo "Processing repository: $repo_name"
        echo "================================================"
        
        # Verify the repository exists in workspace
        if [ ! -d "/workspace/$repo_name" ]; then
            echo "WARNING: Repository directory /workspace/$repo_name not found, skipping..."
            continue
        fi
        
        # Read configuration for this repo from repo_config.yaml
        PROBLEM_STATEMENT_TYPE=$(python3 -c "
import yaml
try:
    with open('/app/repo_config.yaml', 'r') as f:
        config = yaml.safe_load(f)
    repo_name = '$repo_name'
    if 'repositories' in config and repo_name in config['repositories']:
        repo_config = config['repositories'][repo_name]
        if 'problem_statement' in repo_config:
            print(repo_config['problem_statement'].get('type', 'text'))
        else:
            print('text')
    else:
        print('text')
except Exception as e:
    print('text')
")
        
        PROBLEM_STATEMENT_GITHUB_URL=$(python3 -c "
import yaml
try:
    with open('/app/repo_config.yaml', 'r') as f:
        config = yaml.safe_load(f)
    repo_name = '$repo_name'
    if 'repositories' in config and repo_name in config['repositories']:
        repo_config = config['repositories'][repo_name]
        if 'problem_statement' in repo_config:
            print(repo_config['problem_statement'].get('github_url', ''))
        else:
            print('')
    else:
        print('')
except:
    print('')
")
        
        PROBLEM_STATEMENT_TEXT=$(python3 -c "
import yaml
try:
    with open('/app/repo_config.yaml', 'r') as f:
        config = yaml.safe_load(f)
    repo_name = '$repo_name'
    if 'repositories' in config and repo_name in config['repositories']:
        repo_config = config['repositories'][repo_name]
        if 'problem_statement' in repo_config:
            print(repo_config['problem_statement'].get('text', ''))
        else:
            print('')
    else:
        print('')
except:
    print('')
")
        
        echo "========================================"
        echo "PROBLEM STATEMENT DEBUG INFO:"
        echo "  Type: '$PROBLEM_STATEMENT_TYPE'"
        echo "  GitHub URL: '$PROBLEM_STATEMENT_GITHUB_URL'"
        echo "  Text: '$PROBLEM_STATEMENT_TEXT'"
        echo "  Repository: '$repo_name'"
        echo "  Repository path: '/workspace/$repo_name'"
        echo "========================================"
        
        # Clean up tools directory before each repo to avoid conflicts
        echo "Cleaning tools directory for fresh setup..."
        rm -rf /root/tools 2>/dev/null || true
        mkdir -p /root/tools
        
        # Run the worker agent for this repository
        if [ "$PROBLEM_STATEMENT_TYPE" = "github_migration" ] && [ -n "$PROBLEM_STATEMENT_GITHUB_URL" ]; then
            echo "✅ Using github_migration problem statement"
            echo "   Command: --problem_statement.type=github_migration --problem_statement.github_url=\"$PROBLEM_STATEMENT_GITHUB_URL\""
            python sweagent/run/run.py run \
              --config=./config/interactive_consultant.yaml \
              --env.deployment.type=local \
              --env.repo.type=preexisting \
              --env.repo.repo_name="/workspace/$repo_name" \
              --problem_statement.type=github_migration \
              --problem_statement.github_url="$PROBLEM_STATEMENT_GITHUB_URL"
        elif [ "$PROBLEM_STATEMENT_TYPE" = "text" ] && [ -n "$PROBLEM_STATEMENT_TEXT" ]; then
            echo "✅ Using text problem statement from config"
            echo "   Text: \"$PROBLEM_STATEMENT_TEXT\""
            python sweagent/run/run.py run \
              --config=./config/interactive_consultant.yaml \
              --env.deployment.type=local \
              --env.repo.type=preexisting \
              --env.repo.repo_name="/workspace/$repo_name" \
              --problem_statement.type=text \
              --problem_statement.text="$PROBLEM_STATEMENT_TEXT"
        else
            echo "⚠️ No problem statement found in config, using default"
            python sweagent/run/run.py run \
              --config=./config/interactive_consultant.yaml \
              --env.deployment.type=local \
              --env.repo.type=preexisting \
              --env.repo.repo_name="/workspace/$repo_name" \
              --problem_statement.type=text \
              --problem_statement.text="Code migration task for $repo_name"
        fi
        
        echo "Completed processing: $repo_name"
        echo ""
    done
else
    # Process specific repository
    echo "Processing specific repo: $REPO_NAME"
    
    # Verify the repository exists in workspace
    if [ ! -d "/workspace/$REPO_NAME" ]; then
        echo "ERROR: Repository directory /workspace/$REPO_NAME not found!"
        exit 1
    fi
    
    # Read configuration for this specific repo
    if [ -f "/app/repo_config.yaml" ]; then
        echo "Reading repo_config.yaml for repo: $REPO_NAME"
        PROBLEM_STATEMENT_TYPE=$(python3 -c "
import yaml
import os
try:
    with open('/app/repo_config.yaml', 'r') as f:
        config = yaml.safe_load(f)
    repo_name = os.environ.get('REPO_NAME', '')
    if 'repositories' in config and repo_name in config['repositories']:
        repo_config = config['repositories'][repo_name]
        if 'problem_statement' in repo_config:
            print(repo_config['problem_statement'].get('type', 'text'))
        else:
            print('text')
    else:
        print('text')
except Exception as e:
    print('text', file=__import__('sys').stderr)
    print(f'Error: {e}', file=__import__('sys').stderr)
")
        
        PROBLEM_STATEMENT_GITHUB_URL=$(python3 -c "
import yaml
import os
try:
    with open('/app/repo_config.yaml', 'r') as f:
        config = yaml.safe_load(f)
    repo_name = os.environ.get('REPO_NAME', '')
    if 'repositories' in config and repo_name in config['repositories']:
        repo_config = config['repositories'][repo_name]
        if 'problem_statement' in repo_config:
            print(repo_config['problem_statement'].get('github_url', ''))
        else:
            print('')
    else:
        print('')
except:
    print('')
")
        
        PROBLEM_STATEMENT_TEXT=$(python3 -c "
import yaml
import os
try:
    with open('/app/repo_config.yaml', 'r') as f:
        config = yaml.safe_load(f)
    repo_name = os.environ.get('REPO_NAME', '')
    if 'repositories' in config and repo_name in config['repositories']:
        repo_config = config['repositories'][repo_name]
        if 'problem_statement' in repo_config:
            print(repo_config['problem_statement'].get('text', ''))
        else:
            print('')
    else:
        print('')
except:
    print('')
")
        
        echo "========================================"
        echo "PROBLEM STATEMENT DEBUG INFO:"
        echo "  Type: '$PROBLEM_STATEMENT_TYPE'"
        echo "  GitHub URL: '$PROBLEM_STATEMENT_GITHUB_URL'"
        echo "  Text: '$PROBLEM_STATEMENT_TEXT'"
        echo "========================================"
    else
        echo "ERROR: repo_config.yaml not found!"
        exit 1
    fi
    
    # Run the worker agent for the specific repository
    if [ "$PROBLEM_STATEMENT_TYPE" = "github_migration" ] && [ -n "$PROBLEM_STATEMENT_GITHUB_URL" ]; then
        echo "✅ Using github_migration problem statement"
        echo "   URL: $PROBLEM_STATEMENT_GITHUB_URL"
        python sweagent/run/run.py run \
          --config=./config/interactive_consultant.yaml \
          --env.deployment.type=local \
          --env.repo.type=preexisting \
          --env.repo.repo_name="/workspace/$REPO_NAME" \
          --problem_statement.type=github_migration \
          --problem_statement.github_url="$PROBLEM_STATEMENT_GITHUB_URL"
    elif [ "$PROBLEM_STATEMENT_TYPE" = "text" ] && [ -n "$PROBLEM_STATEMENT_TEXT" ]; then
        echo "✅ Using text problem statement from config"
        echo "   Text: \"$PROBLEM_STATEMENT_TEXT\""
        python sweagent/run/run.py run \
          --config=./config/interactive_consultant.yaml \
          --env.deployment.type=local \
          --env.repo.type=preexisting \
          --env.repo.repo_name="/workspace/$REPO_NAME" \
          --problem_statement.type=text \
          --problem_statement.text="$PROBLEM_STATEMENT_TEXT"
    else
        echo "⚠️ No problem statement found in config, using default"
        python sweagent/run/run.py run \
          --config=./config/interactive_consultant.yaml \
          --env.deployment.type=local \
          --env.repo.type=preexisting \
          --env.repo.repo_name="/workspace/$REPO_NAME" \
          --problem_statement.type=text \
          --problem_statement.text="Code migration task for $REPO_NAME"
    fi
fi

echo "Worker completed all tasks"
