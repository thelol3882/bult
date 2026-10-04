# bult — dev tasks. Run `make help` for the list.

NODES       ?= bult-node-1 bult-node-2
AGENT_BIN   := agent/bin/bultd
VERSION     := $(shell git describe --tags --always --dirty 2>/dev/null || echo dev)
AGENT_GOOS   ?= linux
AGENT_GOARCH ?= arm64
AGENT_LDFLAGS := -X main.version=$(VERSION)

.DEFAULT_GOAL := help
.PHONY: help proto proto-breaking agent-build agent-vet agent-test agent-deploy agent-clean nodes

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

# multipass transfer drops the exec bit, so install with explicit mode.
# Nodes that are not Running are skipped with a warning; fails only if none got the binary.
agent-deploy: agent-build ## Build and install bultd to /usr/local/bin on running NODES
	@deployed=0; \
	for n in $(NODES); do \
		if ! multipass list --format csv | grep -q "^$$n,Running,"; then \
			echo "-- $$n: not running, skipped"; continue; \
		fi; \
		echo "-> $$n"; \
		multipass transfer $(AGENT_BIN) $$n:/tmp/bultd && \
		multipass exec $$n -- sudo install -m 755 /tmp/bultd /usr/local/bin/bultd && \
		multipass exec $$n -- rm -f /tmp/bultd || exit 1; \
		deployed=$$((deployed + 1)); \
	done; \
	if [ $$deployed -eq 0 ]; then echo "no running nodes — start one with: multipass start <name>"; exit 1; fi

agent-clean: ## Remove agent build output
	rm -rf agent/bin

## --- nodes -------------------------------------------------------------

nodes: ## List node VMs and their IPs
	@multipass list

# TODO: restart bultd systemd unit after agent-deploy.
# TODO: compose up/down for the host stack.
