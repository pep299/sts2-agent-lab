"""同じ公開観測用Mentorをlearnの公開ホストで実行する。"""

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
import traceback
import subprocess
import tomllib

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / 'backends/learn_dll'))
sys.path.insert(0, str(REPO / 'backends/common'))
from learn_environment import LearnEnvironment
from policy_io import JsonLinePolicy, DeclaredLimit
from policy import default_config


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
    search = tomllib.loads(args.config.read_text())['search']
    for key, value in [('sims', args.sims), ('boss_sims', args.boss_sims)]:
        if value is not None:
            search[key] = value
    source_commit = subprocess.check_output(['git', '-C', str(args.learn_root), 'rev-parse', 'HEAD'], text=True).strip()
    if subprocess.check_output(['git', '-C', str(args.learn_root), 'status', '--porcelain', '--untracked-files=no'], text=True).strip():
        parser.error('learnソースに未コミット変更がある')
    output = args.output.resolve()
    if not output.is_relative_to(REPO / 'local/learn_dll/results'):
        parser.error('出力はlocal/learn_dll/results内に指定')
    env = LearnEnvironment(args.learn_root, args.dotnet, output)
    policy = None
    report = {'backend': 'learn_dll', 'outcome': 'interrupted', 'terminal': None,
              'dataValid': False, 'expertData': False, 'steps': 0,
              'sims': search['sims'], 'bossSims': search['boss_sims'],
              'publicOnlyPolicy': True, 'gameEquivalenceCertified': False}
    started = time.monotonic()
    deadline = started + args.seconds
    try:
        (output / 'replay-input.private.json').write_text(json.dumps({
            'seed': args.seed, 'character': 'IRONCLAD', 'ascension': 0,
            'actGeneration': 'seeded_all_unlocked', 'sims': search['sims'],
            'bossSims': search['boss_sims'], 'threads': search['threads'],
            'learnCommit': source_commit,
            'hostSha256': hashlib.sha256(env.host.read_bytes()).hexdigest(),
            'seconds': args.seconds, 'maxSteps': args.max_steps,
            'selectionFallback': args.allow_selection_fallback,
            'configSha256': hashlib.sha256(args.config.read_bytes()).hexdigest(),
            'policyInput': False}, ensure_ascii=False, indent=2) + '\n')
        command = [sys.executable, '-B', str(REPO / 'agents/mentor/policy.py'),
                   '--config', str(args.config), '--backend', 'learn']
        for flag, value in [('--sims', args.sims), ('--boss-sims', args.boss_sims)]:
            if value is not None:
                command += [flag, str(value)]
        if args.allow_selection_fallback:
            command.append('--allow-selection-fallback')
        report['faultOwner'] = 'policy'
        policy = JsonLinePolicy(command,
                output / 'policy-stderr.log')
        report['faultOwner'] = 'environment'
        env.reset(args.seed, deadline)
        previous_room = None
        while not env.last['observation']['state']['terminal']:
            if env.steps >= args.max_steps or time.monotonic() >= deadline:
                report['interruptionReason'] = 'declared_limit'
                break
            state = env.last['observation']['state']
            status = state['status']
            room = status['act'], status['floor']
            if room != previous_room:
                print(json.dumps({'act': room[0], 'floor': room[1], 'hp': status['hp'],
                                  'phase': state['phase'], 'steps': env.steps}), flush=True)
                previous_room = room
            report['faultOwner'] = 'policy'
            decision = policy(env.last, run_deadline=deadline)
            report['faultOwner'] = 'environment'
            env.step(decision, deadline)
        terminal = env.last['observation']['state']['terminal']
        if terminal:
            report.update(outcome='completed', terminal=terminal, dataValid=True)
        report.pop('faultOwner', None)
    except DeclaredLimit as error:
        report.update(outcome='interrupted', interruptionReason=str(error))
        report.pop('faultOwner', None)
    except TimeoutError as error:
        if time.monotonic() >= deadline:
            report.update(outcome='interrupted', interruptionReason='declared_wall_time_limit')
            report.pop('faultOwner', None)
        else:
            report.update(outcome='fault', error=str(error), traceback=traceback.format_exc())
    except Exception as error:
        report.update(outcome='fault', error=str(error), traceback=traceback.format_exc())
    finally:
        if policy:
            policy.close()
        env.close()
        report.update(steps=env.steps, wallSeconds=time.monotonic() - started,
                      processReaped=env.process.poll() is not None, exitCode=env.process.returncode)
        host_errors = [line for line in (output / 'host-stderr.log').read_text().splitlines()
                       if '[ERROR]' in line]
        unexpected_exit = env.process.returncode != 0 and report['outcome'] != 'interrupted'
        if unexpected_exit or host_errors:
            report.update(outcome='fault', terminal=None, dataValid=False,
                          faultOwner='environment', hostErrorLines=host_errors,
                          error=report.get('error', 'learn_host_exit_or_error_log'))
        if env.last:
            state = env.last['observation']['state']
            report['lastState'] = {k: state['status'][k] for k in ('act', 'floor', 'hp', 'maxHp')}
            report['lastState']['phase'] = state['phase']
            (output / 'last-public-boundary.json').write_text(json.dumps(env.last, ensure_ascii=False))
        for name in ('events.jsonl', 'policy-stderr.log'):
            if (output / name).is_file():
                report[name + 'Sha256'] = hashlib.sha256((output / name).read_bytes()).hexdigest()
        (output / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps({k: v for k, v in report.items() if k != 'traceback'}, ensure_ascii=False), flush=True)
    if report['outcome'] == 'fault':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
