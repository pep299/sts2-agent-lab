SIM := external/sts2-sim/Sts2Sim.sln

.PHONY: setup build-all build-sim

setup:
	@if [ -e .git ]; then git submodule update --init --recursive; fi

build-all: build-sim

build-sim: setup
	dotnet test $(SIM) -c Release
