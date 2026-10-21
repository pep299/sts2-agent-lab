#!/usr/bin/env bash
set -euo pipefail

bundle="$RUNNER_TEMP/sts2-chat"
mkdir -p "$bundle/source" "$bundle/nuget" dist

git ls-files --recurse-submodules -z |
  tar --null -T - -cf - |
  tar -C "$bundle/source" -xf -

cp packaging/NuGet.Offline.Config "$bundle/NuGet.Config"
tar -C "$bundle" -czf dist/sts2-chat.tar.gz dotnet nuget source NuGet.Config
