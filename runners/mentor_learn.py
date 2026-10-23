"""Mentor方策とlearn公開観測ホストの組み合わせを起動する。"""
import argparse
import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agents.mentor.runtime import default_config
from backends.learn_dll.batch import run_episode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--learn-root', type=Path, default=REPO / 'external/learn-the-spire')
    parser.add_argument('--dotnet', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seed', required=True)
    parser.add_argument('--config', type=Path, default=default_config())
    parser.add_argument('--sims', type=int)
    parser.add_argument('--boss-sims', type=int)
    parser.add_argument('--seconds', type=int, default=900)
    parser.add_argument('--max-steps', type=int, default=5000)
    parser.add_argument('--allow-selection-fallback', action='store_true')
    args = parser.parse_args()
    if min(x for x in (args.sims, args.boss_sims, args.seconds, args.max_steps) if x is not None) <= 0:
        parser.error('探索回数・時間・操作上限は正の整数を指定')
    command = [sys.executable, '-B', '-m', 'agents.mentor.policy', '--config', str(args.config.resolve())]
    for flag, value in [('--sims', args.sims), ('--boss-sims', args.boss_sims)]:
        if value is not None:
            command += [flag, str(value)]
    if args.allow_selection_fallback:
        command.append('--allow-selection-fallback')
    report = run_episode(args.learn_root, args.dotnet, args.output, args.seed, command,
                         seconds=args.seconds, max_steps=args.max_steps, policy_cwd=REPO)
    print(json.dumps(report, ensure_ascii=False))
    raise SystemExit(1 if report['outcome'] == 'fault' else 0)


if __name__ == '__main__':
    main()
