"""公開JSON境界を受け付けるMentor方策のプロセス入口。"""
import argparse
import json
from pathlib import Path
import sys
import traceback

from agents.mentor.policy import Mentor
from agents.mentor.runtime import REPO, default_config, sha
from agents.mentor.noncombat import UnscoredSelection


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=default_config())
    parser.add_argument('--sims', type=int)
    parser.add_argument('--boss-sims', type=int)
    parser.add_argument('--allow-selection-fallback', action='store_true',
                        help='モデルで採点できないカード選択のみ、先頭の必要枚数で代替する（任意なら空）。版・再生不一致は停止する')
    args = parser.parse_args()
    policy = Mentor(args.config)
    policy.selection_fallback = args.allow_selection_fallback
    for key, value in [('sims', args.sims), ('boss_sims', args.boss_sims)]:
        if value is not None:
            if value <= 0:
                parser.error('探索回数は正の整数を指定')
            policy.search[key] = value
    sources = [REPO / name for name in (
        'agents/mentor/__main__.py', 'agents/mentor/policy.py', 'agents/mentor/runtime.py', 'agents/mentor/noncombat.py',
        'agents/mentor/combat.py', 'agents/mentor/nested_combat.py',
        'sts2/observation.py', 'sts2/selection.py')]
    print(json.dumps({'kind': 'policy_initialized', **policy.identity,
                      'selection_fallback': policy.selection_fallback,
                      'search': policy.search, 'config_sha256': sha(args.config),
                      'source_sha256': {str(path.relative_to(REPO)): sha(path) for path in sources}},
                     ensure_ascii=False), file=sys.stderr, flush=True)
    for line in sys.stdin:
        if line.strip():
            try:
                boundary = json.loads(line)
                try:
                    response = policy.choose(boundary)
                except UnscoredSelection as error:
                    response = policy.fallback_selection(boundary, error)
            except Exception as error:
                traceback.print_exc(file=sys.stderr)
                response = {'error': str(error), 'error_type': type(error).__name__}
            print(json.dumps(response), flush=True)


if __name__ == '__main__':
    main()
