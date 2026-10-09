# bult — dev tasks. Run `make help` for the list.

NODES        ?= bult-node-1 bult-node-2 bult-builder
BUILDER_NODE ?= bult-builder
REGISTRY     ?= 192.168.252.1:5050
AGENT_BIN    := agent/bin/bultd
AGENT_UNIT   := deploy/systemd/bultd.service
VERSION     := $(shell git describe --tags --always --dirty 2>/dev/null || echo dev)
AGENT_GOOS   ?= linux
AGENT_GOARCH ?= arm64
AGENT_LDFLAGS := -X main.version=$(VERSION)

.DEFAULT_GOAL := help
.PHONY: help proto proto-breaking agent-build agent-vet agent-test agent-setup agent-deploy agent-status agent-logs agent-clean nodes

help: ## Show available targets
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z_-]+:.*## / {printf "  %-14s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

## --- contract ----------------------------------------------------------

proto: ## Format, lint and regenerate Go + Python code from proto/
	buf format -w
	buf lint
	buf generate

# Compares against main: run before committing changes to an existing contract.
proto-breaking: ## Check proto changes for backward compatibility
	buf breaking --against '.git#branch=main'

## --- agent -------------------------------------------------------------

# Phony on purpose: make can't track Go deps; go's build cache keeps rebuilds fast.
agent-build: ## Cross-compile bultd for the nodes into agent/bin/
	cd agent && CGO_ENABLED=0 GOOS=$(AGENT_GOOS) GOARCH=$(AGENT_GOARCH) \
		go build -ldflags "$(AGENT_LDFLAGS)" -o bin/bultd ./cmd/bultd
	@echo "built $(AGENT_BIN) $(VERSION) ($(AGENT_GOOS)/$(AGENT_GOARCH))"

agent-vet: ## go vet the agent
	cd agent && go vet ./...

agent-test: ## Run agent tests
	cd agent && go test ./...

# Runs a shell snippet on every Running node in NODES ($$n = node name).
# Stopped nodes are skipped with a warning; fails if no node was reachable.
define for_running_nodes
	@done=0; \
	for n in $(NODES); do \
		if ! multipass list --format csv | grep -q "^$$n,Running,"; then \
			echo "-- $$n: not running, skipped"; continue; \
		fi; \
		echo "-> $$n"; \
		$(1) || exit 1; \
		done=$$((done + 1)); \
	done; \
	if [ $$done -eq 0 ]; then echo "no running nodes — start one with: multipass start <name>"; exit 1; fi
endef

# One-time (idempotent) node preparation: the bultd system user in the docker
# group, and the builder's environment file with its role and registry.
# Runner nodes get no env file: the unit treats it as optional.
agent-setup: ## Create the bultd user on NODES and the builder's /etc/bult/bultd.env
	$(call for_running_nodes, \
		multipass exec $$n -- sudo sh -c 'id bultd >/dev/null 2>&1 || useradd --system --no-create-home --shell /usr/sbin/nologin --groups docker bultd' && \
		if [ "$$n" = "$(BUILDER_NODE)" ]; then \
			multipass exec $$n -- sudo sh -c 'mkdir -p /etc/bult && printf "BULTD_ARGS=--role builder --registry $(REGISTRY)\n" > /etc/bult/bultd.env' && \
			echo "   $$n: role builder; registry $(REGISTRY)"; \
		fi)

# multipass transfer drops the exec bit, so install with explicit modes.
# `restart` after `enable --now`: picks up the new binary if the unit was already running.
agent-deploy: agent-build ## Install bultd + its systemd unit on running NODES and restart it
	$(call for_running_nodes, \
		multipass transfer $(AGENT_BIN) $$n:/tmp/bultd && \
		multipass transfer $(AGENT_UNIT) $$n:/tmp/bultd.service && \
		multipass exec $$n -- sudo sh -c 'pkill -x bultd -u ubuntu 2>/dev/null; \
			install -m 755 /tmp/bultd /usr/local/bin/bultd && \
			install -m 644 /tmp/bultd.service /etc/systemd/system/bultd.service && \
			rm -f /tmp/bultd /tmp/bultd.service && \
			systemctl daemon-reload && systemctl enable --now bultd && systemctl restart bultd' && \
		multipass exec $$n -- systemctl is-active bultd)

agent-status: ## Show bultd service status on running NODES
	$(call for_running_nodes, \
		multipass exec $$n -- systemctl status bultd --no-pager --lines=0 | head -4)

# Usage: make agent-logs NODE=bult-builder [LINES=50]
agent-logs: ## Show the last journald lines of bultd on NODE
	@test -n "$(NODE)" || { echo "usage: make agent-logs NODE=<node> [LINES=50]"; exit 1; }
	multipass exec $(NODE) -- journalctl -u bultd --no-pager -n $(or $(LINES),50)

agent-clean: ## Remove agent build output
	rm -rf agent/bin

## --- nodes -------------------------------------------------------------

nodes: ## List node VMs and their IPs
	@multipass list

# TODO: compose up/down for the host stack.
