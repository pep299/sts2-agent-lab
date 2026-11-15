PYTHON ?= python3
NATIVE_SRC := backends/native_headless/src
NATIVE_OUTPUT ?= local/native_headless/results/verification-001

.PHONY: native-prepare native-build native-test native-verify

native-prepare:
	$(PYTHON) $(NATIVE_SRC)/setup.py

native-build:
	$(PYTHON) $(NATIVE_SRC)/build.py

native-test:
	PYTHONPATH=$(NATIVE_SRC) $(PYTHON) -m unittest discover -s backends/native_headless/tests

native-verify:
	PYTHONPATH=$(NATIVE_SRC) $(PYTHON) backends/native_headless/tests/integration.py --output $(NATIVE_OUTPUT)

MENTOR_CARGO ?= cargo
MENTOR_CARGO_FLAGS ?=
MENTOR_SOURCE := external/spire-mentor
MENTOR_TARGET := $(CURDIR)/local/mentor/target
MENTOR_LIB_EXT := $(if $(filter Darwin,$(shell uname -s)),dylib,so)

.PHONY: mentor-deps mentor-build mentor-test mentor-chat-test sts2-test

mentor-deps:
	git submodule update --init --recursive $(MENTOR_SOURCE)

mentor-build:
	cd $(MENTOR_SOURCE)/sts2-rs && CARGO_TARGET_DIR="$(MENTOR_TARGET)" PYO3_PYTHON="$(PYTHON)" "$(MENTOR_CARGO)" build -p sts2-py --lib --features pyo3/extension-module --locked --release $(MENTOR_CARGO_FLAGS)
	cp "$(MENTOR_TARGET)/release/libsts2_rs.$(MENTOR_LIB_EXT)" local/mentor/sts2_rs.abi3.so

.PHONY: transport-test

transport-test:
	$(PYTHON) -B -m unittest discover -s backends/common/tests

mentor-test:
	$(PYTHON) -B -m unittest discover -s agents/mentor/tests

mentor-chat-test:
	PYTHONPATH=chat:local/mentor $(PYTHON) -B -m unittest discover -s chat/tests

sts2-test:
	$(PYTHON) -B -m unittest discover -s sts2/tests

.PHONY: event-test

event-test:
	$(PYTHON) -B -m unittest discover -s tests/events -p 'test_*.py'
