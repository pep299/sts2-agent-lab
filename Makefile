SIM := external/sts2-sim/Sts2Sim.sln

.PHONY: setup build-all build-sim

setup:
	git submodule update --init --recursive external/sts2-sim

build-all: build-sim

build-sim:
	dotnet build $(SIM) -c Release

NATIVE_PYTHON ?= python3
NATIVE_SRC := backends/native_headless/src
NATIVE_OUTPUT ?= local/native_headless/results/verification-001

.PHONY: native-prepare native-build native-test native-verify

native-prepare:
	$(NATIVE_PYTHON) $(NATIVE_SRC)/setup.py

native-build:
	$(NATIVE_PYTHON) $(NATIVE_SRC)/build.py

native-test:
	PYTHONPATH=$(NATIVE_SRC) $(NATIVE_PYTHON) -m unittest discover -s backends/native_headless/tests

native-verify:
	PYTHONPATH=$(NATIVE_SRC) $(NATIVE_PYTHON) backends/native_headless/tests/integration.py --output $(NATIVE_OUTPUT)

MENTOR_PYTHON ?= python3
MENTOR_CARGO ?= cargo

.PHONY: mentor-setup mentor-build mentor-test

mentor-setup:
	git submodule update --init --recursive external/spire-mentor

mentor-build:
	$(MENTOR_PYTHON) -B agents/mentor/build.py --cargo $(MENTOR_CARGO)

mentor-test:
	$(MENTOR_PYTHON) -B -m unittest discover -s agents/mentor/tests

LEARN_DOTNET ?= dotnet
LEARN_GAME_LIBS ?=

.PHONY: learn-setup learn-build learn-test

learn-setup:
	git submodule update --init --recursive external/learn-the-spire

learn-build:
	@test -n "$(LEARN_GAME_LIBS)" || (echo 'LEARN_GAME_LIBSに既存の管理DLLディレクトリを指定してください'; exit 1)
	cd external/learn-the-spire && "$(LEARN_DOTNET)" build addons/public-observation/public-observation.sln -c Release -p:GameLibDir="$(abspath $(LEARN_GAME_LIBS))"

learn-test:
	$(MENTOR_PYTHON) -B -m unittest discover -s backends/learn_dll/tests
