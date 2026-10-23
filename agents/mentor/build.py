"""固定したMentorソースから推論用Rust拡張をビルドする。"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib

REPO = Path(__file__).resolve().parents[2]
SOURCE = REPO / 'external/spire-mentor'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cargo', default='cargo')
    parser.add_argument('--jobs', type=int, default=2)
    parser.add_argument('--offline', action='store_true')
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error('jobsは正の整数を指定')
    config = tomllib.loads((REPO / 'config/mentor.example.toml').read_text())
    actual = subprocess.check_output(['git', '-C', str(SOURCE), 'rev-parse', 'HEAD'], text=True).strip()
    if actual != config['identity']['build_git']:
        parser.error('Mentorのcheckoutが設定の固定commitと一致しない')
    if subprocess.check_output(['git', '-C', str(SOURCE), 'status', '--porcelain', '--untracked-files=no'], text=True).strip():
        parser.error('Mentorソースに未コミット変更がある')
    model = REPO / config['paths']['model']
    if hashlib.sha256(model.read_bytes()).hexdigest() != config['identity']['model_sha256']:
        parser.error('モデルのSHA256が固定値と一致しない')
    if sys.platform not in {'darwin', 'linux'}:
        parser.error('このビルド入口はmacOS/Linux用')
    output = REPO / 'local/mentor'
    output.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, CARGO_TARGET_DIR=str(output / 'target'), PYO3_PYTHON=sys.executable)
    cargo = shutil.which(args.cargo)
    if cargo is None:
        parser.error('導入済みcargoをPATHまたは--cargoで指定')
    env['PATH'] = str(Path(cargo).parent) + os.pathsep + env.get('PATH', '')
    command = [cargo, 'build', '--locked', '--release', '-p', 'sts2-py',
               '--features', 'pyo3/extension-module', '--jobs', str(args.jobs)]
    if args.offline:
        command.append('--offline')
    subprocess.run(command, cwd=SOURCE / 'sts2-rs', env=env, check=True)
    filename = 'libsts2_rs.dylib' if sys.platform == 'darwin' else 'libsts2_rs.so'
    destination = REPO / config['paths']['extension']
    shutil.copy2(output / 'target/release' / filename, destination)
    print(json.dumps({'sourceCommit': actual, 'extension': str(destination),
                      'extensionSha256': hashlib.sha256(destination.read_bytes()).hexdigest()}, ensure_ascii=False))


if __name__ == '__main__':
    main()
