"""既存のPython拡張、会話手順、再生補助をmentor-chatへまとめる。"""

import argparse
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def git(path, *args):
    return subprocess.check_output(["git", "-C", str(path), *args], text=True).strip()


def package(output, extension):
    output.mkdir(parents=True, exist_ok=True)
    mentor = ROOT / "external/spire-mentor"
    files = {
        "sts2_rs.abi3.so": extension,
        "mentor_chat.py": ROOT / "chat/mentor_chat.py",
        "START_HERE.md": ROOT / "chat/START_HERE.md",
        "USER_GUIDE.md": ROOT / "chat/USER_GUIDE.md",
        "LICENSE": mentor / "LICENSE",
        "NOTICE": mentor / "NOTICE",
        "LICENSE-rust": mentor / "sts2-rs/LICENSE",
    }
    for name, source in files.items():
        shutil.copy2(source, output / name)
    shutil.copytree(mentor / "sts2-pycli/data/ppo", output / "models", dirs_exist_ok=True)

    spec = importlib.util.spec_from_file_location("sts2_rs", output / "sts2_rs.abi3.so")
    engine = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(engine)
    probes = {}
    for version in ("v0.111.0", "v0.113.0"):
        try:
            run = engine.RunManager(seed=7, game_version=version)
            probes[version] = {"accepted": True, "reported_version": run.game_version}
        except ValueError as exc:
            probes[version] = {"accepted": False, "error": str(exc)}
    text_versions = []
    for version in probes:
        source = mentor / "sts2-pycli" / f"localization_eng_{version}"
        if source.is_dir():
            destination = output / "localization" / version
            shutil.copytree(source, destination, dirs_exist_ok=True)
            text_versions.append(version)
            for path in destination.rglob("*"):
                if path.is_file():
                    files[str(path.relative_to(output))] = path
    manifest = dict(
        format="mentor-chat-package-v1", lab_commit=git(ROOT, "rev-parse", "HEAD"),
        lab_dirty=bool(git(ROOT, "status", "--porcelain", "--untracked-files=no")),
        mentor_commit=git(mentor, "rev-parse", "HEAD"),
        mentor_dirty=bool(git(mentor, "status", "--porcelain", "--untracked-files=no")),
        workflow_run_url=(f"https://github.com/{os.environ['GITHUB_REPOSITORY']}"
                          f"/actions/runs/{os.environ['GITHUB_RUN_ID']}"
                          if "GITHUB_RUN_ID" in os.environ else None),
        platform=platform.system(), architecture=platform.machine(),
        python_minimum="3.11", build_python=sys.version.split()[0],
        version_probes=probes,
        localization_versions=text_versions,
        version_probe_scope="Constructor acceptance only; not gameplay completeness or game parity.",
        files={name: sha256((output / name).read_bytes()).hexdigest() for name in files},
    )
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(dict(output=str(output), version_probes=probes), ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--extension", type=Path, default=ROOT / "local/mentor/sts2_rs.abi3.so")
    args = parser.parse_args()
    package(args.output.resolve(), args.extension.resolve())
