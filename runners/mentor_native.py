"""探索予算を指定して、準備済み実Godot headlessでMentorを実行する。"""

import argparse
import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / 'backends/native_headless/src'))
from batch import JsonLinePolicy, run_batch
from runtime import RESULTS
from agents.mentor.runtime import default_config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seed', action='append', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--config', type=Path, default=default_config())
    parser.add_argument('--sims', type=int)
    parser.add_argument('--boss-sims', type=int)
    parser.add_argument('--seconds', type=int, default=600)
    parser.add_argument('--max-steps', type=int, default=1500)
    parser.add_argument('--allow-selection-fallback', action='store_true')
    args = parser.parse_args()
    if min(x for x in (args.sims, args.boss_sims, args.seconds, args.max_steps) if x is not None) <= 0:
        parser.error('探索回数・時間・操作上限は正の整数を指定')
    output = args.output.resolve()
    if not output.is_relative_to(RESULTS) or output.exists():
        parser.error('出力はnative_headlessのresults内の新しいパスを指定')
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, '-B', '-m', 'agents.mentor',
               '--config', str(args.config.resolve())]
    for flag, value in [('--sims', args.sims), ('--boss-sims', args.boss_sims)]:
        if value is not None:
            command += [flag, str(value)]
    if args.allow_selection_fallback:
        command.append('--allow-selection-fallback')
    policy = JsonLinePolicy(command,
             output.with_suffix('.policy-stderr.log'), cwd=REPO)
    try:
        specs = [{'seed': seed, 'runSeconds': args.seconds, 'maxSteps': args.max_steps} for seed in args.seed]
        print(json.dumps(run_batch(specs, output, policy), ensure_ascii=False), flush=True)
    finally:
        policy.close()


if __name__ == '__main__':
    main()
