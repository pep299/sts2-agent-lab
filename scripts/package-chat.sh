#!/usr/bin/env bash
set -euo pipefail

bundle="$RUNNER_TEMP/sts2-chat"
mkdir -p "$bundle/source" "$bundle/nuget" "$bundle/sim" dist

git ls-files --recurse-submodules -z |
  tar --null -T - -cf - |
  tar -C "$bundle/source" -xf -

cp -a external/sts2-sim/src/Sts2Sim.Core/bin/Release/net9.0/. "$bundle/sim/"

cp packaging/NuGet.Offline.Config "$bundle/NuGet.Config"
cp packaging/chat-dotnet "$bundle/chat-dotnet"
tar -C "$bundle" -czf dist/sts2-chat.tar.gz dotnet nuget source sim NuGet.Config chat-dotnet
