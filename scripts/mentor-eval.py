#!/usr/bin/env python3
"""Evaluate Mentor PPO/MCTS in the pinned Rust full-run simulator."""
import argparse
import json
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--character', choices=('Ironclad', 'Silent', 'Defect', 'Necrobinder', 'Regent'), default='Ironclad')
    parser.add_argument('--policy', choices=('ppo', 'heuristic'), default='ppo')
    parser.add_argument('--seed', type=int, default=1234)
    parser.add_argument('--ascension', type=int, default=0)
    parser.add_argument('--sims', type=int, default=1000)
    parser.add_argument('--boss-sims', type=int, default=4000)
    parser.add_argument('--max-steps', type=int, default=5000)
    args = parser.parse_args()

    assets = Path(__file__).resolve().parent
    sys.path.insert(0, str(assets))
    import mentor_rs

    run = mentor_rs.RunManager(seed=args.seed, character=args.character,
                               ascension_level=args.ascension, game_version='v0.111.0',
                               neow_start=True, act1='roll')
    if args.policy == 'ppo':
        models = list((assets / 'models').glob(f'ppo_fullrun_{args.character.lower()}_*_v0111vocab.onnx'))
        if len(models) != 1:
            raise RuntimeError(f'Expected one PPO model for {args.character}: {models}')
        agent = mentor_rs.PpoRunAgent(seed=args.seed, sims=args.sims,
                                      boss_sims=args.boss_sims, model_path=str(models[0]))
    else:
        agent = mentor_rs.HeuristicRunAgent(seed=args.seed, sims=args.sims,
                                            boss_sims=args.boss_sims)

    steps = 0
    while not run.is_over() and steps < args.max_steps:
        result = agent.step(run)
        if result is None:
            raise RuntimeError(f'Agent stalled after {steps} steps (phase={run.phase()})')
        steps += 1
    print(json.dumps({'character': args.character, 'policy': args.policy,
                      'seed': args.seed, 'ascension': args.ascension,
                      'finished': run.is_over(),
                      'won': run.player_won if run.is_over() else None,
                      'steps': steps}))


if __name__ == '__main__':
    main()
