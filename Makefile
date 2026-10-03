.DEFAULT_GOAL := check
# Keep validation in a stable order, including recursive Python matrix runs.
.NOTPARALLEL:

UV ?= uv
GO ?= go
GOLANGCI_LINT ?= golangci-lint
PYTHON ?= 3.14
PYTHON_VERSIONS ?= 3.10 3.14

# Resolve each interpreter's dependencies without changing .venv or uv.lock.
PYTHON_RUN = "$(UV)" run --no-project --python "$(PYTHON)" --with-editable ".[dev]"
PYTHON_TEST_TARGETS := $(addprefix test-python-,$(PYTHON_VERSIONS))

.PHONY: check lint lint-python lint-go test test-python test-python-matrix \
        test-go build $(PYTHON_TEST_TARGETS)

check: lint test

lint: lint-python lint-go

test: test-python-matrix test-go

lint-python:
	$(PYTHON_RUN) ruff check src/ tests/
	$(PYTHON_RUN) ruff format --check src/ tests/
	$(PYTHON_RUN) lint-imports --no-logo

lint-go:
	"$(GO)" vet ./...
	"$(GOLANGCI_LINT)" run ./...

test-python:
	$(PYTHON_RUN) python -m unittest

test-python-matrix: $(PYTHON_TEST_TARGETS)

$(PYTHON_TEST_TARGETS): test-python-%:
	$(MAKE) test-python PYTHON="$*"

test-go:
	"$(GO)" test ./...

build:
	"$(GO)" build -ldflags="-s -w" ./cmd/manualbook
