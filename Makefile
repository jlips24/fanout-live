SHELL := /bin/sh

SYSTEM_PYTHON ?= python3
VENV ?= .venv
PYTHON ?= $(VENV)/bin/python
PIP ?= $(PYTHON) -m pip
DEV_DEPS_STAMP ?= $(VENV)/.requirements-dev.stamp
CONFIG ?= config.toml
DATA_DIR ?= data
WEB_HOST ?= 0.0.0.0
WEB_PORT ?= 8080
IMAGE ?= remote-multistreamer
TAG ?= local
VERSION ?= $(shell $(SYSTEM_PYTHON) -c 'import tomllib; print(tomllib.load(open("pyproject.toml", "rb"))["project"]["version"])')
FANOUT_LIVE_TAG ?= $(VERSION)
COMPOSE ?= docker compose

.DEFAULT_GOAL := help

.PHONY: help
help: ## Show available make targets.
	@awk 'BEGIN {FS = ":.*## "; printf "\nRemote Multi-Streamer targets:\n\n"} /^[a-zA-Z0-9_-]+:.*## / {printf "  %-18s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

.PHONY: venv
venv: ## Create the local Python virtual environment.
	@if [ ! -x "$(PYTHON)" ]; then $(SYSTEM_PYTHON) -m venv "$(VENV)"; fi

.PHONY: init
init: venv ## Create/persist a local config with a generated OBS key.
	$(PYTHON) -m remote_multistreamer --config "$(CONFIG)" --init-config

.PHONY: test
test: venv ## Run unit tests.
	$(PYTHON) -m unittest discover -s tests

.PHONY: coverage
coverage: deps-dev ## Run unit tests with coverage reporting.
	$(PYTHON) -m coverage run -m unittest discover -s tests
	$(PYTHON) -m coverage report

.PHONY: deps-dev
deps-dev: $(DEV_DEPS_STAMP) ## Install development dependencies into the local venv.

$(DEV_DEPS_STAMP): requirements-dev.txt | venv
	$(PIP) install -r requirements-dev.txt
	@touch "$(DEV_DEPS_STAMP)"

.PHONY: lint
lint: deps-dev ## Run isort and flake8 checks.
	$(PYTHON) -m isort --check-only remote_multistreamer tests
	$(PYTHON) -m flake8 remote_multistreamer tests

.PHONY: compile
compile: venv ## Compile Python files to catch syntax errors.
	$(PYTHON) -m compileall remote_multistreamer tests

.PHONY: check
check: lint test compile compose-config ## Run all fast local checks.

.PHONY: build
build: compile ## Build/check the local Python application.

.PHONY: dry-run
dry-run: venv ## Print the generated ffmpeg command without starting the relay.
	$(PYTHON) -m remote_multistreamer --config "$(CONFIG)" --dry-run

.PHONY: run
run: venv ## Run the relay directly from the local config.
	$(PYTHON) -m remote_multistreamer --config "$(CONFIG)"

.PHONY: run-web
run-web: venv ## Run the web UI locally.
	$(PYTHON) -m remote_multistreamer --web --config "$(CONFIG)" --web-host "$(WEB_HOST)" --web-port "$(WEB_PORT)"

.PHONY: docker-build
docker-build: ## Build the Docker image.
	docker build -t "$(IMAGE):$(TAG)" .

.PHONY: docker-run
docker-run: ## Run the Docker image directly, using ./data for config persistence.
	mkdir -p "$(DATA_DIR)"
	docker run --rm -p 1935:1935 -p 8080:8080 -v "$$(pwd)/$(DATA_DIR):/config" "$(IMAGE):$(TAG)"

.PHONY: compose-config
compose-config: ## Validate docker-compose.yml.
	FANOUT_LIVE_TAG="$(FANOUT_LIVE_TAG)" $(COMPOSE) config

.PHONY: docker-up
docker-up: ## Pull and start the published Compose service in the background.
	mkdir -p "$(DATA_DIR)"
	FANOUT_LIVE_TAG="$(FANOUT_LIVE_TAG)" $(COMPOSE) up -d

.PHONY: docker-down
docker-down: ## Stop and remove the Compose service.
	FANOUT_LIVE_TAG="$(FANOUT_LIVE_TAG)" $(COMPOSE) down

.PHONY: docker-restart
docker-restart: docker-down docker-up ## Restart the Compose service.

.PHONY: docker-logs
docker-logs: ## Follow Compose service logs.
	FANOUT_LIVE_TAG="$(FANOUT_LIVE_TAG)" $(COMPOSE) logs -f

.PHONY: docker-ps
docker-ps: ## Show Compose service status.
	FANOUT_LIVE_TAG="$(FANOUT_LIVE_TAG)" $(COMPOSE) ps

.PHONY: docker-shell
docker-shell: ## Open a shell in the running Compose service container.
	FANOUT_LIVE_TAG="$(FANOUT_LIVE_TAG)" $(COMPOSE) exec remote-multistreamer /bin/sh
