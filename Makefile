SIM := external/sts2-sim/Sts2Sim.sln

.PHONY: setup build-all build-sim

setup:
	git submodule update --init --recursive

build-all: build-sim

build-sim:
	dotnet build $(SIM) -c Release
