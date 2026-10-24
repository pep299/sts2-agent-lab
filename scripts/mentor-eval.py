#!/usr/bin/env python3
"""Evaluate or improve Mentor policies with repeatable full-run simulations.

Optional --policy-file must define choose(run, actions, agent). Return a legal
action dict to override Mentor, or None to retain the baseline decision.
"""
import argparse
from contextlib import nullcontext
import json
from pathlib import Path
import runpy
import sys


CHARACTERS = ('Ironclad', 'Silent', 'Defect', 'Necrobinder', 'Regent')


def evaluate(args, seed, engine, choose, trace):
    assets = Path(__file__).resolve().parent
    run = engine.RunManager(seed=seed, character=args.character,
                            ascension_level=args.ascension, game_version='v0.111.0',
                            neow_start=True, act1='roll')
    if args.policy == 'ppo':
        models = list((assets / 'models').glob(f'ppo_fullrun_{args.character.lower()}_*_v0111vocab.onnx'))
        if len(models) != 1:
            raise RuntimeError(f'Expected exactly one model for {args.character}: {models}')
        agent = engine.PpoRunAgent(seed=seed, sims=args.sims,
                                   boss_sims=args.boss_sims, model_path=str(models[0]))
    else:
        agent = engine.HeuristicRunAgent(seed=seed, sims=args.sims,
                                        boss_sims=args.boss_sims)

    steps = 0
    while not run.is_over() and steps < args.max_steps:
        phase = run.phase()
        action = choose(run, run.available_actions(), agent) if choose else None
        if action is None:
            record = agent.step(run)
            if record is None:
                raise RuntimeError(f'Agent stalled at seed={seed} step={steps} phase={phase}')
            action, result, source = record['action'], record['result'], 'mentor'
        else:
            if action not in run.available_actions():
                raise ValueError(f'Custom policy returned an illegal action: {action}')
            result, source = run.take_action(action), 'custom'
        steps += 1
        if trace is not None:
            trace.write(json.dumps({'seed': seed, 'step': steps, 'phase': phase,
                                    'source': source, 'action': action, 'result': result}) + '\n')

    return {'character': args.character, 'policy': args.policy,
            'seed': seed, 'ascension': args.ascension,
            'finished': run.is_over(),
            'won': run.player_won if run.is_over() else None, 'steps': steps}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--character', choices=CHARACTERS, default='Ironclad')
    parser.add_argument('--policy', choices=('ppo', 'heuristic'), default='ppo')
    parser.add_argument('--policy-file', type=Path,
                        help='Python file defining choose(run, actions, agent) -> action dict or None')
    parser.add_argument('--seed', type=int, default=1234)
    parser.add_argument('--count', type=int, default=1, help='Number of consecutive seeds to evaluate')
    parser.add_argument('--ascension', type=int, default=0)
    parser.add_argument('--sims', type=int, default=1000)
    parser.add_argument('--boss-sims', type=int, default=4000)
    parser.add_argument('--max-steps', type=int, default=5000)
    parser.add_argument('--trace', type=Path, help='Optional JSONL decision log')
    args = parser.parse_args()
    if min(args.count, args.sims, args.boss_sims, args.max_steps) < 1:
        parser.error('count, sims, boss-sims, and max-steps must all be positive')

    assets = Path(__file__).resolve().parent
    sys.path.insert(0, str(assets))
    import mentor_rs

    choose = None
    if args.policy_file:
        choose = runpy.run_path(str(args.policy_file))['choose']
        if not callable(choose):
            parser.error('choose must be callable')

    wins = completed = 0
    with (args.trace.open('w') if args.trace else nullcontext(None)) as trace:
        for seed in range(args.seed, args.seed + args.count):
            result = evaluate(args, seed, mentor_rs, choose, trace)
            print(json.dumps(result), flush=True)
            completed += result['finished']
            wins += result['won'] is True
    if args.count > 1:
        print(json.dumps({'type': 'summary', 'requested': args.count,
                          'finished': completed, 'wins': wins,
                          'win_rate_among_finished': wins / completed if completed else None}))


if __name__ == '__main__':
    main()
