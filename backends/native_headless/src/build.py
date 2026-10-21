"""追跡するmodソースを、追跡しないビルド先・専用アプリへ出力する。"""
from pathlib import Path
import fcntl
import json
import os
import shutil
import subprocess
import tempfile

from configuration import BACKEND, LOCAL, BUILD, LOCK, MANIFEST, load_config, dotnet_command
from runtime import sha, write_json

def build():
    load_config()
    lock = LOCK.open('a+')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    manifest = json.loads(MANIFEST.read_text())
    BUILD.mkdir(parents=True, exist_ok=True)
    environment = os.environ | {'DOTNET_CLI_HOME':str(LOCAL / 'dotnet-home'), 'DOTNET_CLI_TELEMETRY_OPTOUT':'1',
                               'DOTNET_GENERATE_ASPNET_CERTIFICATE':'false'}
    package = Path(manifest['executable']).parent / 'mods/spire-jev-bridge'
    with tempfile.TemporaryDirectory(dir=BUILD) as directory:
        stage = Path(directory) / 'source'
        shutil.copytree(BACKEND / 'mod', stage)
        result = subprocess.run([dotnet_command(), 'build', str(stage / 'SpireJevBridge.csproj'), '-c', 'Release',
                                 '-p:GameDataDir=' + manifest['gameData'], '--ignore-failed-sources'], env=environment,
                                text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        (BUILD / 'build.log').write_text(result.stdout)
        print(result.stdout)
        result.check_returncode()
        package.mkdir(parents=True, exist_ok=True)
        for name in ['spire-jev-bridge.dll', 'spire-jev-bridge.json']:
            shutil.copy2(stage / 'bin/Release/net9.0' / name, package / name)
    manifest['modSha256'] = sha(package / 'spire-jev-bridge.dll')
    manifest['sourceSha256'] = {str(p.relative_to(BACKEND / 'mod')):sha(p) for p in (BACKEND / 'mod').rglob('*.cs')}
    write_json(MANIFEST, manifest)

if __name__ == '__main__':
    build()
