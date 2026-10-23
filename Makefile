SIM := external/sts2-sim/Sts2Sim.sln

.PHONY: chat-bundle-prepare chat-bundle

chat-bundle-prepare:
	git submodule update --init --recursive external/sts2-sim

chat-bundle:
	dotnet build $(SIM) -c Release
	bash scripts/package-chat.sh

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

.PHONY: mentor-deps mentor-build mentor-test sts2-test

mentor-deps:
	git submodule update --init --recursive $(MENTOR_SOURCE)

mentor-build:
	@case "$$(uname -s)" in Darwin|Linux) ;; *) echo 'MentorのビルドはmacOS/Linux用です'; exit 1;; esac
	@test -z "$$(git -C $(MENTOR_SOURCE) status --porcelain --untracked-files=no)" || (echo 'Mentorソースに未コミット変更があります'; exit 1)
	cd $(MENTOR_SOURCE)/sts2-rs && CARGO_TARGET_DIR="$(MENTOR_TARGET)" PYO3_PYTHON="$(PYTHON)" "$(MENTOR_CARGO)" build --locked --release -p sts2-py --features pyo3/extension-module --jobs 2 $(MENTOR_CARGO_FLAGS)
	cp "$(MENTOR_TARGET)/release/libsts2_rs.$(MENTOR_LIB_EXT)" local/mentor/sts2_rs.abi3.so

mentor-test:
	$(PYTHON) -B -m unittest discover -s agents/mentor/tests

sts2-test:
	$(PYTHON) -B -m unittest discover -s sts2/tests

.PHONY: runners-test

runners-test:
	$(PYTHON) -B -m unittest discover -s runners/tests
