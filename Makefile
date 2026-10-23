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

.PHONY: mentor-deps mentor-patch mentor-build mentor-test sts2-test

mentor-deps:
	git submodule update --init --recursive $(MENTOR_SOURCE)

mentor-patch:
	git -C $(MENTOR_SOURCE) apply --reverse --check "$(CURDIR)/patches/spire-mentor/autoplay-resume.patch" 2>/dev/null || git -C $(MENTOR_SOURCE) apply "$(CURDIR)/patches/spire-mentor/autoplay-resume.patch"

mentor-build:
	cd $(MENTOR_SOURCE)/sts2-rs && CARGO_TARGET_DIR="$(MENTOR_TARGET)" PYO3_PYTHON="$(PYTHON)" "$(MENTOR_CARGO)" build --manifest-path "$(CURDIR)/agents/mentor/engine/Cargo.toml" --locked --release --jobs 2 $(MENTOR_CARGO_FLAGS)
	cp "$(MENTOR_TARGET)/release/libmentor_rs.$(MENTOR_LIB_EXT)" local/mentor/mentor_rs.abi3.so

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
