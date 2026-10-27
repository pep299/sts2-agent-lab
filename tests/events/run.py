"""診断用のイベント分岐を強制し、公開観測からMentorで後続処理を実行する。"""
import argparse
from collections import deque
from contextlib import redirect_stderr
import hashlib
from io import StringIO
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import traceback

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from agents.mentor.policy import Mentor
from agents.mentor.runtime import default_config
from backends.learn_dll.learn_environment import LearnEnvironment
from sts2.observation import card_state, metadata

SOURCE_HASHES = {str(path.relative_to(REPO)): hashlib.sha256(path.read_bytes()).hexdigest()
                for folder in ('agents/mentor', 'sts2', 'backends/learn_dll', 'tests/events')
                for path in (REPO / folder).glob('*.py')}


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def public_boundary(boundary):
    obs = boundary['observation']
    return dict({k: v for k, v in boundary.items() if k != 'fixtureInitialization'},
                observation=dict(obs, actions=[a for a in obs['actions']
                if a['kind'] != 'fixture' and not a['id'].startswith('fixture:')]))


def fingerprint(boundary):
    state = boundary['observation']['state']
    # fixtureごとの物理カードIDを除き、分岐の前提となる公開状態を比較する。
    def stable(value):
        if isinstance(value, dict):
            return {k: stable(v) for k, v in value.items() if k not in ('instance', 'identityScope', 'rendered')}
        if isinstance(value, list):
            return [stable(v) for v in value]
        return value
    # 実DLLのTrial.CalculateVarsだけがこの表示番号にRng.Chaoticを使う。
    replay_state = dict(state)
    if state.get('eventId') in ('TRIAL', 'EVENT.TRIAL') and isinstance(state.get('text'), str):
        replay_state['text'] = re.sub(r'Entrant \[blue\][0-9]{3}\[/blue\]',
                                      'Entrant [blue]<cosmetic>[/blue]', state['text'])
    return hashlib.sha256(json.dumps(stable(replay_state), sort_keys=True).encode()).hexdigest()


def event_candidates(boundary):
    obs = boundary['observation']
    if obs['state']['phase'] != 'event':
        return []
    options = {o['index']: o for o in obs['state']['options']}
    return [{'action_id': a['id'], 'option_index': metadata(a)['option_index'],
             'key': options[metadata(a)['option_index']].get('text_key'),
             'relic': options[metadata(a)['option_index']].get('relic')}
            for a in obs['actions'] if a['kind'] == 'event']


def outcome_state(boundary):
    state = boundary['observation']['state']
    status = state['status']
    return {key: status[key] for key in ('hp', 'maxHp', 'gold', 'act', 'floor', 'relics')} | {
        'phase': state['phase'], 'terminal': state['terminal'],
        'deck': [card_state(card) for card in status['deckCards']], 'potions': status['potionBelt'],
        **({'relicDetails': status['relicDetails']} if 'relicDetails' in status else {})}


class LearnFixture(LearnEnvironment):
    def __init__(self, args, output):
        self.output = output
        output.mkdir(parents=True, exist_ok=False)
        self.host = args.fixture_host.resolve()
        self.stderr = (output / 'host-stderr.log').open('x')
        try:
            command = [str(args.dotnet), str(self.host), '--host-dir', str(args.learn_host_dir), '--log', str(output / 'events.jsonl')]
            self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=self.stderr, bufsize=0, cwd=REPO)
        except BaseException:
            self.stderr.close()
            raise
        os.set_blocking(self.process.stdout.fileno(), False)
        self.timeout = args.seconds
        self.steps = self.decision_id = 0
        self.last = None
        self.deadline = time.monotonic() + args.seconds

    def begin(self, event, args):
        return self.request({'cmd': 'reset_event', 'eventName': event['name'], 'seed': args.seed,
                             'hp': args.hp, 'maxHp': args.max_hp, 'gold': args.gold,
                             **getattr(args, 'fixture', {})}, self.deadline)

    def step(self, decision):
        return super().step(decision, self.deadline)


class NativeFixture:
    def __init__(self, args, output):
        sys.path.insert(0, str(REPO / 'backends/native_headless/src'))
        from runtime import NativeEnvironment
        self.env = NativeEnvironment(output, args.seed, fixture=True, run_seconds=args.seconds,
            max_steps=args.max_steps, event_fixture={'event': event_id(args.event), 'hp': args.hp,
                'max_hp': args.max_hp, 'gold': args.gold, **getattr(args, 'fixture', {})})

    def begin(self, event, args):
        result = self.env.start()
        return dict(result, fixtureInitialization=self.env.report.get('fixtureInitialization'))

    @property
    def last(self):
        return self.env.last

    def step(self, decision):
        return self.env.step(decision['action_id'], indices=decision.get('indices'))

    def close(self):
        return self.env.close()


def event_id(event):
    return event['id'].split('.', 1)[-1]


def fixed_case(name, path=Path(__file__).with_name('cases.json')):
    manifest = json.loads(path.read_text())
    names = [case['name'] for case in manifest['cases']]
    if len(names) != len(set(names)):
        raise ValueError('固定case名が重複')
    if name not in names:
        raise ValueError('未知の固定case: ' + name)
    spec = dict(manifest['defaults']) | manifest['cases'][names.index(name)]
    allowed = {'name', 'event', 'seed', 'hp', 'max_hp', 'gold', 'fixture', 'expect'}
    if spec.keys() != allowed or any(type(spec[k]) is not int for k in ('hp', 'max_hp', 'gold')):
        raise ValueError('固定caseのフィールドが不正')
    if not isinstance(spec['seed'], str) or re.fullmatch(r'[A-Za-z0-9]{1,64}', spec['seed']) is None:
        raise ValueError('固定caseのseedが不正')
    if not 1 <= spec['hp'] <= spec['max_hp'] or spec['gold'] < 0:
        raise ValueError('固定caseのHP/goldが不正')
    fixture = (path.parent / spec['fixture']).resolve()
    if not fixture.is_relative_to((path.parent / 'fixtures').resolve()):
        raise ValueError('固定caseのfixtureはfixtures内に指定')
    spec['fixture'] = json.loads(fixture.read_text())
    if (not isinstance(spec['fixture'], dict)
            or not spec['fixture'].keys() <= {'act', 'potions', 'add_cards', 'relics', 'deck'}
            or type(spec['fixture'].get('act')) is not int or spec['fixture']['act'] not in (1, 2, 3)):
        raise ValueError('固定caseのfixtureが不正')
    expect = spec['expect']
    if not isinstance(expect, dict) or not expect or not expect.keys() <= {'present', 'absent', 'branches'}:
        raise ValueError('固定caseの期待が不正')
    if any(not isinstance(value, list) for value in expect.values()) or not any(expect.values()):
        raise ValueError('固定caseの期待を一つ以上指定')
    selectors = expect.get('present', []) + expect.get('absent', [])
    for branch in expect.get('branches', []):
        if (not isinstance(branch, dict) or set(branch) != {'selected', 'phases', 'terminal'}
                or not isinstance(branch['phases'], list)
                or any(not isinstance(phase, str) or not phase for phase in branch['phases'])
                or branch['terminal'] not in (None, 'death', 'victory')):
            raise ValueError('固定caseの分岐期待が不正')
        selectors.append(branch['selected'])
    for selector in selectors:
        if (not isinstance(selector, dict) or not selector.keys() <= {'key', 'option_index'}
                or not isinstance(selector.get('key'), str) or not selector['key']
                or 'option_index' in selector and (type(selector['option_index']) is not int or selector['option_index'] < 0)):
            raise ValueError('固定caseの候補指定が不正')
    return spec


def check_expectations(spec, records):
    def matches(candidate, selector):
        return all(candidate.get(key) == value for key, value in selector.items())

    missing = []
    expected_condition = {key: spec[key] for key in ('seed', 'hp', 'max_hp', 'gold')}
    expected_condition['maxHp'] = expected_condition.pop('max_hp')
    expected_condition |= {'character': 'IRONCLAD', 'ascension': 0} | spec['fixture']
    expected_before = {key: expected_condition[key] for key in ('hp', 'maxHp', 'gold', 'act')}
    def correct_input(record):
        return (record.get('initialCondition') == expected_condition
                and record.get('event', {}).get('name') == spec['event']
                and all(record.get('before', {}).get(key) == value for key, value in expected_before.items()))

    completed = [record for record in records if record['status'] == 'completed' and correct_input(record)]
    if any(record.get('initialCondition') != expected_condition for record in records):
        missing.append({'initialCondition': '固定caseの初期条件と記録が不一致'})
    if any(not correct_input(record) for record in records):
        missing.append({'before': '固定caseのイベント/HP/gold/actと公開開始状態が不一致'})
    initials = [record['trace'][0]['candidates'] for record in completed if record.get('trace')]
    for kind in ('present', 'absent'):
        for selector in spec['expect'].get(kind, []):
            counts = [sum(matches(candidate, selector) for candidate in candidates) for candidates in initials]
            if not counts or any(count != (1 if kind == 'present' else 0) for count in counts):
                missing.append({kind: selector})
    for branch in spec['expect'].get('branches', []):
        found = False
        for record in completed:
            for position, step in enumerate(record['trace']):
                candidates = [c for c in step['candidates'] if matches(c, branch['selected'])]
                if len(candidates) != 1 or candidates[0]['action_id'] != step['response']['action_id']:
                    continue
                following = record['trace'][position + 1:]
                next_event = next((i for i, child in enumerate(following) if child['candidates']), len(following))
                phases = {child['phase'] for child in following[:next_event]}
                found |= (set(branch['phases']) <= phases and record['after']['terminal'] == branch['terminal'])
        if not found:
            missing.append({'branch': branch})
    return missing


def succeeded(summary):
    return (bool(summary['cases']) and all(row['status'] == 'completed' for row in summary['cases'])
            and summary.get('regression', {}).get('passed', True))


def one_case(args, event, prefix, output, schedule, executed):
    started = time.monotonic()
    env = None
    report = {'event': event, 'backend': args.backend, 'fixture': True, 'expertData': False,
              'prefix': prefix, 'status': 'fault', 'semanticEffectVerified': False,
              'coverage': 'event-option branches at one declared initial state; card combinations and RNG outcomes not exhaustive',
              'sourceSha256': SOURCE_HASHES,
              'policyDeadline': 'cooperative between in-process inference calls; host communication has a deadline',
              'initialCondition': {'character': 'IRONCLAD', 'ascension': 0, 'seed': args.seed,
                                   'hp': args.hp, 'maxHp': args.max_hp, 'gold': args.gold,
                                   **getattr(args, 'fixture', {})},
              'trace': [], 'mentorDecisions': 0, 'forcedDecisions': 0}
    try:
        args.event = event
        env = LearnFixture(args, output) if args.backend == 'learn' else NativeFixture(args, output)
        raw = env.begin(event, args)
        if 'fixtureInitialization' in raw:
            report['fixtureInitialization'] = raw['fixtureInitialization']
        elif args.backend == 'learn':
            initializations = [json.loads(line)['data'] for line in (output / 'events.jsonl').read_text().splitlines()
                              if json.loads(line)['kind'] == 'event_fixture_initialized']
            report['fixtureInitialization'] = initializations[-1] if initializations else None
        boundary = public_boundary(raw)
        state = boundary['observation']['state']
        if state['phase'] == 'event' and state.get('eventId') and state['eventId'].split('.', 1)[-1] != event_id(event):
            raise ValueError('要求したイベントと実際のイベントが異なる')
        report['before'] = outcome_state(boundary)
        policy = Mentor(args.policy_config)
        policy.context.reset()
        report['policyIdentity'] = policy.identity
        report['selectionFallback'] = policy.selection_fallback
        event_path = []
        for step in range(args.max_steps):
            if time.monotonic() - started > args.seconds:
                report.update(status='limit', reason='wall_time')
                break
            obs = boundary['observation']
            phase = obs['state']['phase']
            if phase == 'map' or obs['state']['terminal']:
                if len(event_path) < len(prefix):
                    raise ValueError('強制分岐の末尾に到達する前にイベントが終了')
                report.update(status='completed' if report['trace'] else 'no_public_decision', after=outcome_state(boundary))
                break
            candidates = event_candidates(boundary)
            signature = fingerprint(boundary)
            forced = candidates and len(event_path) < len(prefix)
            diagnostic = None
            if forced:
                selected = prefix[len(event_path)]
                if signature != selected['state']:
                    raise ValueError('強制分岐の再生前提が変化')
                if not any(c['action_id'] == selected['action_id'] for c in candidates):
                    raise ValueError('強制する選択肢が公開候補にない')
            for candidate in candidates:
                schedule(event_path + [dict(candidate, state=signature)])
            if forced:
                response = {'action_id': selected['action_id']}
                policy.noncombat.prepare(obs)
                policy.noncombat.remember(obs, response)
                policy.context.remember(obs, response)
                report['forcedDecisions'] += 1
            else:
                captured = StringIO()
                with redirect_stderr(captured):
                    response = policy.choose(boundary)
                diagnostic = json.loads(captured.getvalue())
                report['mentorDecisions'] += 1
            if candidates:
                event_path.append(dict(next(c for c in candidates if c['action_id'] == response['action_id']), state=signature))
            report['trace'].append({'phase': phase, 'forced': bool(forced), 'state': signature,
                'response': response, 'candidates': candidates, 'diagnostic': diagnostic})
            env.step(response)
            if candidates:
                executed.add((signature, response['action_id']))
            boundary = public_boundary(env.last)
        else:
            state = boundary['observation']['state']
            if (state['phase'] == 'map' or state['terminal']) and len(event_path) >= len(prefix):
                report.update(status='completed', after=outcome_state(boundary))
            else:
                report.update(status='limit', reason='step_count')
    except Exception as error:
        report.update(error=str(error), errorType=type(error).__name__, traceback=traceback.format_exc())
        if env is not None and env.last:
            write(output / 'last-public-boundary.json', env.last)
    finally:
        if env is not None:
            closing = env.close()
            if args.backend == 'learn':
                report.update(processReaped=env.process.poll() is not None, exitCode=env.process.returncode)
                errors = [line for line in (output / 'host-stderr.log').read_text().splitlines() if '[ERROR]' in line]
                if env.process.returncode != 0 or errors:
                    report.update(status='fault', shutdownOrHostErrors=errors)
            else:
                report['nativeResult'] = closing
                report.update(processReaped=closing['processReaped'], exitCode=closing.get('exitCode'))
                if (closing.get('unreviewedNativeErrorCount') or closing.get('faultCategory')
                        or closing.get('exitCode') != 0 or closing['processReaped'] is not True):
                    report.update(status='fault', shutdownOrHostErrors=closing.get('error') or
                                  'Native終了時のexitCode/processReaped/エラー記録が正常ではない')
        report['seconds'] = time.monotonic() - started
        output.mkdir(parents=True, exist_ok=True)
        write(output / 'case.json', report)
    return report


def run(args):
    catalog = json.loads(args.catalog.read_text())
    events = catalog['events']
    if args.events:
        events = [e for e in events if e['name'] in args.events or event_id(e) in args.events]
        if len(events) != len(set(args.events)):
            raise ValueError('指定されたイベントの一部が一覧にない／重複')
    output = args.output.resolve()
    if not output.is_relative_to(REPO / 'local'):
        raise ValueError('出力はlocal内に指定')
    output.mkdir(parents=True, exist_ok=False)
    rows = []
    for event in events:
        if event.get('category') == 'special' and not getattr(args, 'include_special', False):
            rows.append({'event': event['name'], 'status': 'unsupported_fixture', 'reason': '通常出現プール外。専用の終盤状態が必要'})
            continue
        queue = deque([[]])
        scheduled = {()}
        states = set()
        executed = set()
        def schedule(prefix):
            edge = (prefix[-1]['state'], prefix[-1]['action_id'])
            if edge in states:
                return
            states.add(edge)
            key = tuple((p['state'], p['action_id']) for p in prefix)
            if key not in scheduled:
                scheduled.add(key)
                queue.append(prefix)
        count = 0
        while queue and count < args.max_paths:
            prefix = queue.popleft()
            if prefix and (prefix[-1]['state'], prefix[-1]['action_id']) in executed:
                continue
            folder = output / event['name'] / f'{count:03d}'
            result = one_case(args, event, prefix, folder, schedule, executed)
            rows.append({'event': event['name'], 'case': str(folder.relative_to(output)), 'status': result['status'],
                         'error': result.get('error'), 'mentorDecisions': result['mentorDecisions'],
                         'forcedDecisions': result['forcedDecisions']})
            print(json.dumps(rows[-1], ensure_ascii=False), flush=True)
            write(output / 'summary.json', {'backend': args.backend, 'fixture': True, 'expertData': False, 'cases': rows})
            count += 1
        if queue:
            rows.append({'event': event['name'], 'status': 'limit', 'unexecutedPaths': len(queue)})
    summary = {'backend': args.backend, 'fixture': True, 'expertData': False, 'cases': rows,
               'allBranchesVerified': False, 'scope': 'declared initial condition; no proof of full conditional or semantic coverage'}
    if getattr(args, 'case_spec', None) is not None:
        records = [json.loads((output / row['case'] / 'case.json').read_text()) for row in rows if row.get('case')]
        missing = check_expectations(args.case_spec, records)
        summary['regression'] = {'name': args.case_spec['name'], 'missing': missing,
                                 'passed': succeeded(summary) and not missing}
    write(output / 'summary.json', summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend', choices=['learn', 'native'], required=True)
    parser.add_argument('--catalog', type=Path, default=Path(__file__).with_name('catalog.json'))
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument('--events', nargs='+')
    selection.add_argument('--case', help='cases.jsonの固定条件・期待を再実行（1設定）')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--dotnet', type=Path)
    parser.add_argument('--fixture-host', type=Path, default=REPO / 'local/learn_dll/event-fixture/bin/Release/net9.0/EventFixture.dll')
    parser.add_argument('--learn-host-dir', type=Path)
    parser.add_argument('--policy-config', type=Path, default=default_config())
    parser.add_argument('--fixture', type=Path, help='追加のact/potions/add_cards/relics/deckを記載したJSON')
    parser.add_argument('--include-special', action='store_true')
    parser.add_argument('--seed')
    parser.add_argument('--hp', type=int)
    parser.add_argument('--max-hp', type=int)
    parser.add_argument('--gold', type=int)
    parser.add_argument('--max-paths', type=int, default=64)
    parser.add_argument('--max-steps', type=int, default=200)
    parser.add_argument('--seconds', type=int, default=120)
    args = parser.parse_args()
    if args.case:
        if any(value is not None for value in (args.fixture, args.seed, args.hp, args.max_hp, args.gold)):
            parser.error('--caseの初期条件は固定。--fixture/seed/hp/max-hp/goldは併用不可')
        try:
            args.case_spec = fixed_case(args.case)
        except (OSError, KeyError, TypeError, ValueError) as error:
            parser.error(str(error))
        args.events = [args.case_spec['event']]
        for key in ('seed', 'hp', 'max_hp', 'gold', 'fixture'):
            setattr(args, key, args.case_spec[key])
        args.include_special = True
    else:
        for key, default in {'seed': 'EVENTCOVER111', 'hp': 40, 'max_hp': 80, 'gold': 100}.items():
            if getattr(args, key) is None:
                setattr(args, key, default)
    if args.fixture and not args.case:
        args.fixture = json.loads(args.fixture.read_text())
        if not isinstance(args.fixture, dict) or not args.fixture.keys() <= {'act', 'potions', 'add_cards', 'relics', 'deck'}:
            parser.error('fixtureの追加フィールドが不正')
    elif not args.case:
        args.fixture = {}
    if args.backend == 'learn' and (args.dotnet is None or args.learn_host_dir is None):
        parser.error('learnには--dotnetと--learn-host-dirが必要')
    if min(args.max_paths, args.max_steps, args.seconds, args.hp, args.max_hp) < 1 or args.hp > args.max_hp or args.gold < 0:
        parser.error('実行上限は正数、1 <= hp <= max-hp、gold >= 0を指定')
    result = run(args)
    raise SystemExit(0 if succeeded(result) else 1)


if __name__ == '__main__':
    main()
