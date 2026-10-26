"""公開観測ホストでJSON Lines方策を実行し、ラン結果と障害を記録する。"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time
import traceback

from backends.common.policy_io import JsonLinePolicy, DeclaredLimit, PolicyFault
from backends.learn_dll.learn_environment import LearnEnvironment

REPO = Path(__file__).resolve().parents[2]


def run_episode(root, dotnet, output, seed, policy_command, *, seconds=900, max_steps=5000, policy_cwd=REPO, crystal_assets=None):
    if min(seconds, max_steps) <= 0:
        raise ValueError('時間・操作上限は正の整数を指定')
    root = Path(root).resolve()
    output = Path(output)
    source_commit = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
    if subprocess.check_output(['git', '-C', str(root), 'status', '--porcelain', '--untracked-files=no'], text=True).strip():
        raise ValueError('learnソースに未コミット変更がある')
    output = output.resolve()
    if not output.is_relative_to(REPO / 'local/learn_dll/results'):
        raise ValueError('出力はlocal/learn_dll/results内に指定')
    environment_options = {'crystal_assets': crystal_assets} if crystal_assets is not None else {}
    env = LearnEnvironment(root, dotnet, output, **environment_options)
    policy = None
    report = {'backend': 'learn_dll', 'outcome': 'interrupted', 'terminal': None,
              'dataValid': False, 'expertData': False, 'steps': 0,
              'policyInputScope': 'public_observation_and_actions', 'gameEquivalenceCertified': False}
    started = time.monotonic()
    deadline = started + seconds
    try:
        (output / 'replay-input.private.json').write_text(json.dumps({
            'seed': seed, 'character': 'IRONCLAD', 'ascension': 0,
            'actGeneration': 'seeded_all_unlocked', 'policyCommand': policy_command,
            'learnCommit': source_commit,
            'hostSha256': hashlib.sha256(env.host.read_bytes()).hexdigest(),
            'crystalAssetsDirectory': str(Path(crystal_assets).resolve()) if crystal_assets is not None else None,
            'crystalAssetsSha256': hashlib.sha256((Path(crystal_assets) / 'catalog.json').read_bytes()).hexdigest() if crystal_assets is not None else None,
            'seconds': seconds, 'maxSteps': max_steps,
            'environmentSourceSha256': {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                for path in [Path(__file__), Path(__file__).with_name('observation.py'),
                             Path(__file__).with_name('learn_environment.py')]},
            'policyInput': False}, ensure_ascii=False, indent=2) + '\n')
        report['faultOwner'] = 'policy'
        policy = JsonLinePolicy(policy_command, output / 'policy-stderr.log', cwd=policy_cwd)
        report['faultOwner'] = 'environment'
        env.reset(seed, deadline)
        previous_room = None
        while not env.last['observation']['state']['terminal']:
            if env.steps >= max_steps or time.monotonic() >= deadline:
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
    except PolicyFault as error:
        report.update(outcome='fault', faultOwner='policy', error=str(error), traceback=traceback.format_exc())
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
        missing_log = report['outcome'] == 'completed' and not (output / 'events.jsonl').is_file()
        if unexpected_exit or host_errors or missing_log:
            report.update(outcome='fault', terminal=None, dataValid=False,
                          faultOwner='environment', hostErrorLines=host_errors,
                          error=report.get('error', 'learn_host_exit_or_error_or_missing_log'))
        if env.last:
            state = env.last['observation']['state']
            report['lastState'] = {k: state['status'][k] for k in ('act', 'floor', 'hp', 'maxHp')}
            report['lastState']['phase'] = state['phase']
            (output / 'last-public-boundary.json').write_text(json.dumps(env.last, ensure_ascii=False))
        for name in ('events.jsonl', 'policy-stderr.log'):
            if (output / name).is_file():
                report[name + 'Sha256'] = hashlib.sha256((output / name).read_bytes()).hexdigest()
        (output / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--learn-root', type=Path, default=REPO / 'external/learn-the-spire')
    parser.add_argument('--dotnet', type=Path, required=True)
    parser.add_argument('--crystal-assets', type=Path, help='同じゲーム版から抽出した公開画像資産ディレクトリ')
    parser.add_argument('--seed', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seconds', type=int, default=900)
    parser.add_argument('--max-steps', type=int, default=5000)
    parser.add_argument('--policy-cwd', type=Path, default=REPO,
                        help='方策プロセスの作業ディレクトリ。既定はこのリポジトリ')
    parser.add_argument('--policy-command', nargs=argparse.REMAINDER, required=True)
    args = parser.parse_args()
    if not args.policy_command:
        parser.error('--policy-command以降に方策のコマンドを指定')
    report = run_episode(args.learn_root, args.dotnet, args.output, args.seed, args.policy_command,
                         seconds=args.seconds, max_steps=args.max_steps, policy_cwd=args.policy_cwd,
                         crystal_assets=args.crystal_assets)
    print(json.dumps(report, ensure_ascii=False))
    raise SystemExit(1 if report['outcome'] == 'fault' else 0)


if __name__ == '__main__':
    main()
