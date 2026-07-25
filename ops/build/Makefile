# Operator surface for one autonomous HackSome Build Team.

.PHONY: init shared check-init up up-local down down-local build build-local \
	build-agent-local validate validate-local logs logs-lead logs-hub \
	logs-workers logs-verifiers sh sh-lead

TEAM ?= hackathon-team
ACCOUNT ?= foundagent
REPO_ROOT := $(abspath ../..)
OPS_ROOT := $(CURDIR)
PY := $(shell test -x $(REPO_ROOT)/.venv/bin/python && echo $(REPO_ROOT)/.venv/bin/python || echo python3)
PYTHON := PYTHONPATH=$(REPO_ROOT)/src $(PY)
COMPOSE := HACKSOME_ROOT=$(REPO_ROOT) BUILD_OPS_ROOT=$(OPS_ROOT) \
	TEAM=$(TEAM) ACCOUNT=$(ACCOUNT) docker compose -f $(OPS_ROOT)/docker-compose.yml
BASE_REGISTRY ?= registry-1.docker.io
CONTROL_BASE_REGISTRY ?= m.daocloud.io/docker.io/library
CUA_BASE_IMAGE ?= foundagent/cua-ubuntu:local
CUA_AGENT_IMAGE ?= foundagent/cua-agent:local
UBUNTU_APT_MIRROR ?= https://mirrors.tuna.tsinghua.edu.cn/ubuntu
UBUNTU_PORTS_MIRROR ?= https://mirrors.tuna.tsinghua.edu.cn/ubuntu-ports
NPM_REGISTRY ?= https://registry.npmmirror.com
LOCAL_COMPOSE := HACKSOME_ROOT=$(REPO_ROOT) BUILD_OPS_ROOT=$(OPS_ROOT) \
	TEAM=$(TEAM) ACCOUNT=$(ACCOUNT) \
	BASE_REGISTRY=$(BASE_REGISTRY) CONTROL_BASE_REGISTRY=$(CONTROL_BASE_REGISTRY) \
	CUA_AGENT_IMAGE=$(CUA_AGENT_IMAGE) \
	docker compose -f $(OPS_ROOT)/docker-compose.yml \
	-f $(OPS_ROOT)/docker-compose.local.yml

# Usage:
# make init TEAM=my-team CHALLENGE_FILE=/abs/challenge.md IDEA_CARD_FILE=/abs/idea.md
init:
	test -n "$(CHALLENGE_FILE)"
	test -n "$(IDEA_CARD_FILE)"
	$(PYTHON) -m hacksome.stages.build.control.team_store \
		--root $(OPS_ROOT)/state/$(TEAM) \
		--challenge-file "$(CHALLENGE_FILE)" \
		--idea-card-file "$(IDEA_CARD_FILE)"
	chmod -R ugo+rwX $(OPS_ROOT)/state/$(TEAM)

shared:
	mkdir -p $(OPS_ROOT)/state/$(TEAM)/project \
		$(OPS_ROOT)/state/$(TEAM)/ledger \
		$(OPS_ROOT)/state/$(TEAM)/inbox \
		$(OPS_ROOT)/state/$(TEAM)/workers \
		$(OPS_ROOT)/state/$(TEAM)/reviews \
		$(OPS_ROOT)/state/$(TEAM)/control \
		$(OPS_ROOT)/state/$(TEAM)/memory \
		$(OPS_ROOT)/state/$(TEAM)/sessions/lead/codex \
		$(OPS_ROOT)/state/$(TEAM)/telemetry/services \
		$(OPS_ROOT)/state/$(TEAM)/telemetry/runs \
		$(OPS_ROOT)/accounts/$(ACCOUNT)
	chmod -R ugo+rwX $(OPS_ROOT)/state/$(TEAM)

check-init:
	test -f $(OPS_ROOT)/state/$(TEAM)/project/reference/challenge.md
	test -f $(OPS_ROOT)/state/$(TEAM)/project/reference/initial-idea-card.md

up: shared check-init
	$(COMPOSE) up -d --build

up-local: shared check-init build-agent-local
	$(LOCAL_COMPOSE) up -d --build

down:
	$(COMPOSE) stop
	@docker ps -q --filter "label=hacksome.team=$(TEAM)" | while read -r id; do \
		docker stop --time 10 "$$id"; \
	done
	@docker ps -aq --filter "label=hacksome.team=$(TEAM)" | while read -r id; do \
		docker rm -f "$$id"; \
	done
	$(COMPOSE) down --remove-orphans

down-local:
	$(LOCAL_COMPOSE) stop
	@docker ps -q --filter "label=hacksome.team=$(TEAM)" | while read -r id; do \
		docker stop --time 10 "$$id"; \
	done
	@docker ps -aq --filter "label=hacksome.team=$(TEAM)" | while read -r id; do \
		docker rm -f "$$id"; \
	done
	$(LOCAL_COMPOSE) down --remove-orphans

build:
	$(COMPOSE) build hub

build-agent-local:
	docker build \
		--build-arg "BASE_REGISTRY=$(BASE_REGISTRY)" \
		-f $(OPS_ROOT)/docker/Dockerfile.local \
		-t "$(CUA_BASE_IMAGE)" \
		$(OPS_ROOT)/docker
	docker build \
		--build-arg "CUA_BASE_IMAGE=$(CUA_BASE_IMAGE)" \
		--build-arg "UBUNTU_APT_MIRROR=$(UBUNTU_APT_MIRROR)" \
		--build-arg "UBUNTU_PORTS_MIRROR=$(UBUNTU_PORTS_MIRROR)" \
		--build-arg "NPM_REGISTRY=$(NPM_REGISTRY)" \
		-f $(OPS_ROOT)/docker/agent.Dockerfile \
		-t "$(CUA_AGENT_IMAGE)" \
		$(REPO_ROOT)

build-local: build-agent-local
	$(LOCAL_COMPOSE) build hub

validate:
	$(COMPOSE) config >/dev/null
	$(PYTHON) -m compileall -q $(REPO_ROOT)/src/hacksome/stages/build
	$(PYTHON) -m pytest $(REPO_ROOT)/tests/stages/build -q

validate-local:
	$(LOCAL_COMPOSE) config >/dev/null
	$(PYTHON) -m pytest \
		$(REPO_ROOT)/tests/stages/build/control/test_compose_accounts.py -q

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
