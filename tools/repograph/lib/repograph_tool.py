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
    parser.add_argument("--source-module", required=True, help="Source module name")
    parser.add_argument("--source-qualpath", help="Source qualpath (optional)")

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
        "source_module": args.source_module,
    }

    if args.source_qualpath:
        request_data["source_qualpath"] = args.source_qualpath

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
