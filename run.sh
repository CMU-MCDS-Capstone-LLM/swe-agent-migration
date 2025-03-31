#!/usr/bin/env bash
python sweagent/run/run.py run \
	--agent.model.name=openai/gpt-4o-mini \
	--agent.model.per_instance_cost_limit=0.10 \
	--env.repo.github_url=https://github.com/adithyabsk/keep2roam \
	--problem_statement.type=github_migration \
	--problem_statement.github_url=https://github.com/adithyabsk/keep2roam/commit/d340eea2
