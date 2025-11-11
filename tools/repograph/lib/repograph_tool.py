#!/usr/bin/env python3
"""
RepoGraph tool implementation for SWE-agent.
"""

import argparse
import json
import sys

import requests


def main():
    parser = argparse.ArgumentParser(description="RepoGraph query tool")
    parser.add_argument(
        "--server-host", required=True, help="RepoGraph server hostname (network alias)"
    )
    parser.add_argument("--repo-path", required=True, help="Repository path")
    parser.add_argument("--migration-config", help="Migration config YAML path")
    parser.add_argument("--source-module", help="Source module name")
    parser.add_argument("--source-qualpath", help="Source qualpath")
    parser.add_argument(
        "--workspace-symbols", nargs="*", default=[], help="Workspace symbols"
    )
    parser.add_argument("--env-python", help="Python interpreter path")
    parser.add_argument("--extra-paths", nargs="*", default=[], help="Extra paths")

    args = parser.parse_args()

    server_url = f"http://{args.server_host}:8000"

    try:
        health_response = requests.get(f"{server_url}/health", timeout=5)
        if health_response.status_code != 200:
            print(f"Error: Server health check failed", file=sys.stderr)
            sys.exit(1)
    except requests.exceptions.RequestException as e:
        print(f"Error: Cannot connect to RepoGraph server: {e}", file=sys.stderr)
        sys.exit(1)

    # Build request payload
    request_data = {
        "repo_path": args.repo_path,
    }

    if args.migration_config:
        request_data["migration_config"] = args.migration_config
    if args.source_module:
        request_data["source_module"] = args.source_module
    if args.source_qualpath:
        request_data["source_qualpath"] = args.source_qualpath
    if args.env_python:
        request_data["env_python"] = args.env_python
    if args.extra_paths:
        request_data["extra_paths"] = list(args.extra_paths)
    if args.workspace_symbols:
        request_data["workspace_symbols"] = list(args.workspace_symbols)

    try:
        response = requests.post(f"{server_url}/run", json=request_data, timeout=600)
        response.raise_for_status()
        result = response.json()
        print(json.dumps(result, indent=2))

    except requests.exceptions.Timeout:
        print("Error: Query timed out", file=sys.stderr)
        sys.exit(1)
    except requests.exceptions.RequestException as e:
        print(f"Error: {e}", file=sys.stderr)
        if hasattr(e, "response") and e.response is not None:
            try:
                print(f"Server error: {e.response.json()}", file=sys.stderr)
            except:
                print(f"Server response: {e.response.text}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
