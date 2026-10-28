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
	cd $(MENTOR_SOURCE)/sts2-rs && CARGO_TARGET_DIR="$(MENTOR_TARGET)" PYO3_PYTHON="$(PYTHON)" "$(MENTOR_CARGO)" build -p sts2-py --lib --features pyo3/extension-module --locked --release $(MENTOR_CARGO_FLAGS)
	cp "$(MENTOR_TARGET)/release/libsts2_rs.$(MENTOR_LIB_EXT)" local/mentor/sts2_rs.abi3.so

.PHONY: transport-test

transport-test:
	$(PYTHON) -B -m unittest discover -s backends/common/tests

mentor-test:
	$(PYTHON) -B -m unittest discover -s agents/mentor/tests

sts2-test:
	$(PYTHON) -B -m unittest discover -s sts2/tests

LEARN_DOTNET ?= dotnet
LEARN_GAME_LIBS ?=

.PHONY: learn-deps learn-build learn-test

learn-deps:
	git submodule update --init --recursive external/learn-the-spire

learn-build:
	@test -n "$(LEARN_GAME_LIBS)" || (echo 'LEARN_GAME_LIBSに既存の管理DLLディレクトリを指定してください'; exit 1)
	cd external/learn-the-spire && "$(LEARN_DOTNET)" build addons/public-observation/public-observation.sln -c Release -p:GameLibDir="$(abspath $(LEARN_GAME_LIBS))"

learn-test:
	$(PYTHON) -B -m unittest discover -s backends/learn_dll/tests

.PHONY: event-fixture-build event-test

event-fixture-build:
	"$(LEARN_DOTNET)" build backends/learn_dll/fixtures/EventFixture.csproj -c Release -p:BaseOutputPath="$(CURDIR)/local/learn_dll/event-fixture/bin/" -p:BaseIntermediateOutputPath="$(CURDIR)/local/learn_dll/event-fixture/obj/"

event-test:
	$(PYTHON) -B -m unittest discover -s tests/events -p 'test_*.py'
