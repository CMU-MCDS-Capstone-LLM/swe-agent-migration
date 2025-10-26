#!/bin/bash
# Script to start the worker agent and process repositories

echo "Worker starting..."

python -m sweagent.run.run run \
	--env.deployment.type=local \
	--config=./config/code_mig_default.yaml \
	--agent.model.per_instance_cost_limit=0.05 \
	--env.repo.github_url=https://github.com/adithyabsk/keep2roam \
	--problem_statement.type=github_migration \
	--problem_statement.github_url=https://github.com/adithyabsk/keep2roam/commit/d340eea2
