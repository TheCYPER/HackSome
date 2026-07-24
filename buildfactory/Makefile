# Single autonomous Hackathon Team runtime.

.PHONY: init shared check-init up down build validate logs logs-lead logs-hub \
	logs-workers logs-verifiers sh sh-lead

TEAM ?= hackathon-team
ACCOUNT ?= foundagent
TEAM_STATE_ROOT ?= $(abspath state/$(TEAM))
COMPOSE := TEAM=$(TEAM) ACCOUNT=$(ACCOUNT) TEAM_STATE_ROOT=$(TEAM_STATE_ROOT) docker compose
PY := $(shell test -x .venv-cua/bin/python && echo .venv-cua/bin/python || echo python3)

# Usage:
# make init TEAM=my-team CHALLENGE_FILE=/abs/challenge.md IDEA_CARD_FILE=/abs/idea.md
init:
	test -n "$(CHALLENGE_FILE)"
	test -n "$(IDEA_CARD_FILE)"
	$(PY) -m orchestration.team_store \
		--root "$(TEAM_STATE_ROOT)" \
		--challenge-file "$(CHALLENGE_FILE)" \
		--idea-card-file "$(IDEA_CARD_FILE)"
	chmod -R ugo+rwX "$(TEAM_STATE_ROOT)"

shared:
	mkdir -p "$(TEAM_STATE_ROOT)"/project "$(TEAM_STATE_ROOT)"/ledger \
		"$(TEAM_STATE_ROOT)"/inbox "$(TEAM_STATE_ROOT)"/workers \
		"$(TEAM_STATE_ROOT)"/reviews "$(TEAM_STATE_ROOT)"/control \
		"$(TEAM_STATE_ROOT)"/sessions/lead/codex \
		"$(TEAM_STATE_ROOT)"/telemetry/services "$(TEAM_STATE_ROOT)"/telemetry/runs \
		accounts/$(ACCOUNT)
	chmod -R ugo+rwX "$(TEAM_STATE_ROOT)"

check-init:
	test -f "$(TEAM_STATE_ROOT)"/project/reference/challenge.md
	test -f "$(TEAM_STATE_ROOT)"/project/reference/initial-idea-card.md

up: shared check-init
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) stop
	@docker ps -q --filter "label=hacksome.team=$(TEAM)" | while read -r id; do \
		docker stop --time 10 "$$id"; \
	done
	@docker ps -aq --filter "label=hacksome.team=$(TEAM)" | while read -r id; do \
		docker rm -f "$$id"; \
	done
	$(COMPOSE) down --remove-orphans

build:
	$(COMPOSE) build hub

validate:
	$(COMPOSE) config >/dev/null
	$(PY) -m compileall -q agent orchestration
	$(PY) -m pytest orchestration/tests/test_team_runtime.py \
		agent/tests/test_team_loadout.py -q

logs:
	$(COMPOSE) logs -f

logs-lead:
	$(COMPOSE) logs -f lead

logs-hub:
	$(COMPOSE) logs -f hub

logs-workers:
	$(COMPOSE) logs -f worker-manager

logs-verifiers:
	$(COMPOSE) logs -f verifier-manager

sh:
	$(COMPOSE) exec worker-manager sh

sh-lead:
	$(COMPOSE) exec lead bash
