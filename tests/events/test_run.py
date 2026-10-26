import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('event_checks', Path(__file__).with_name('run.py'))
checks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checks)


class EventBoundaries(unittest.TestCase):
    def test_diagnostic_actions_are_not_policy_candidates(self):
        original = {'decision_id': 1, 'fixtureInitialization': {'hiddenFixtureCondition': True}, 'observation': {'actions': [
            {'id': 'event:0', 'kind': 'event'}, {'id': 'fixture:grid2', 'kind': 'fixture'},
            {'id': 'fixture:event', 'kind': 'event'}]}}
        before = copy.deepcopy(original)
        filtered = checks.public_boundary(original)
        self.assertEqual(filtered['observation']['actions'], [{'id': 'event:0', 'kind': 'event'}])
        self.assertNotIn('fixtureInitialization', filtered)
        self.assertEqual(original, before)

    def test_replay_signature_ignores_physical_ids_but_preserves_modifiers_and_costs(self):
        first = {'observation': {'state': {'selection': {'cards': [
            {'state': {'id': 'DEFEND', 'instance': 12, 'identityScope': 'process', 'upgrade': 0,
                       'enchantment': None}}]}, 'status': {'hp': 40, 'gold': 100}}}}
        second = copy.deepcopy(first)
        second['observation']['state']['selection']['cards'][0]['state']['instance'] = 99
        self.assertEqual(checks.fingerprint(first), checks.fingerprint(second))
        second['observation']['state']['selection']['cards'][0]['state']['enchantment'] = {'id': 'SOWN'}
        self.assertNotEqual(checks.fingerprint(first), checks.fingerprint(second))
        second = copy.deepcopy(first)
        second['observation']['state']['status']['gold'] = 0
        self.assertNotEqual(checks.fingerprint(first), checks.fingerprint(second))

    def test_only_trial_cosmetic_entrant_number_is_ignored_for_replay(self):
        first = {'observation': {'state': {'eventId': 'TRIAL', 'text': 'Entrant [blue]160[/blue]',
                                         'options': [{'text_key': 'TRIAL.ACCEPT'}]}}}
        second = copy.deepcopy(first)
        second['observation']['state']['text'] = 'Entrant [blue]186[/blue]'
        self.assertEqual(checks.fingerprint(first), checks.fingerprint(second))
        second['observation']['state']['options'][0]['text_key'] = 'TRIAL.REJECT'
        self.assertNotEqual(checks.fingerprint(first), checks.fingerprint(second))
        second = copy.deepcopy(first)
        second['observation']['state']['text'] += ' A changed trial.'
        self.assertNotEqual(checks.fingerprint(first), checks.fingerprint(second))
        first['observation']['state']['eventId'] = 'OTHER'
        second['observation']['state'].update(eventId='OTHER', text='Entrant [blue]186[/blue]')
        self.assertNotEqual(checks.fingerprint(first), checks.fingerprint(second))

    def test_duplicate_event_keys_remain_distinct_by_public_slot(self):
        boundary = {'observation': {'state': {'phase': 'event', 'options': [
            {'index': 0, 'text_key': 'CHOOSE', 'relic': 'A'},
            {'index': 1, 'text_key': 'CHOOSE', 'relic': 'B'}]}, 'actions': [
                {'id': f'event:{i}', 'kind': 'event', 'detail': {'metadata': {'option_index': i}}}
                for i in range(2)]}}
        candidates = checks.event_candidates(boundary)
        self.assertEqual([c['relic'] for c in candidates], ['A', 'B'])
        self.assertEqual([c['action_id'] for c in candidates], ['event:0', 'event:1'])


class CaseExecution(unittest.TestCase):
    def boundary(self, phase):
        return {'decision_id': 1 if phase == 'event' else 2, 'observation': {
            'state': {'phase': phase, 'terminal': None, 'eventId': 'TEST',
                'status': {'hp': 40, 'maxHp': 80, 'gold': 100, 'act': 1, 'floor': 1,
                           'relics': [], 'deckCards': [], 'potionBelt': {'slots': []}},
                'options': [{'index': 0, 'text_key': 'TEST.START', 'relic': None}]},
            'actions': [{'id': 'event:0', 'kind': 'event', 'detail': {'metadata': {'option_index': 0}}}]}}

    def test_last_permitted_action_can_complete_case(self):
        before, after = self.boundary('event'), self.boundary('map')
        class Environment:
            last = None
            def __init__(self, *args):
                self.last = before
            def begin(self, *args):
                return self.last
            def step(self, response):
                self.last = after
            def close(self):
                return {'processReaped': True, 'exitCode': 0}
        class Policy:
            identity = {}
            selection_fallback = False
            def __init__(self, *args):
                self.context = SimpleNamespace(reset=lambda: None)
            def choose(self, boundary):
                print(json.dumps({'source': 'test'}), file=checks.sys.stderr)
                return {'action_id': 'event:0'}
        args = SimpleNamespace(backend='native', seconds=10, max_steps=1, seed='TEST',
                               hp=40, max_hp=80, gold=100, policy_config=Path('unused'))
        with tempfile.TemporaryDirectory() as folder, patch.object(checks, 'NativeFixture', Environment), patch.object(checks, 'Mentor', Policy):
            report = checks.one_case(args, {'name': 'Test', 'id': 'EVENT.TEST'}, [], Path(folder), lambda _: None, set())
        self.assertEqual(report['status'], 'completed')
        self.assertEqual(report['mentorDecisions'], 1)

    def test_initial_policy_failure_still_schedules_forced_alternatives(self):
        before = self.boundary('event')
        class Environment:
            last = before
            def __init__(self, *args):
                pass
            def begin(self, *args):
                return self.last
            def close(self):
                return {'processReaped': True, 'exitCode': 0}
        class Policy:
            identity = {}
            selection_fallback = False
            def __init__(self, *args):
                self.context = SimpleNamespace(reset=lambda: None)
            def choose(self, boundary):
                raise ValueError('unmapped effect')
        args = SimpleNamespace(backend='native', seconds=10, max_steps=1, seed='TEST',
                               hp=40, max_hp=80, gold=100, policy_config=Path('unused'))
        queued = []
        with tempfile.TemporaryDirectory() as folder, patch.object(checks, 'NativeFixture', Environment), patch.object(checks, 'Mentor', Policy):
            report = checks.one_case(args, {'name': 'Test', 'id': 'EVENT.TEST'}, [], Path(folder), queued.append, set())
        self.assertEqual(report['status'], 'fault')
        self.assertEqual(report['mentorDecisions'], 0)
        self.assertEqual(queued[0][0]['action_id'], 'event:0')

    def test_abnormal_native_exit_cannot_pass_after_reaching_map(self):
        after = self.boundary('map')
        class Environment:
            last = after
            def __init__(self, *args):
                pass
            def begin(self, *args):
                return self.last
            def close(self):
                return {'processReaped': True, 'exitCode': 1}
        class Policy:
            identity = {}
            selection_fallback = False
            def __init__(self, *args):
                self.context = SimpleNamespace(reset=lambda: None)
        args = SimpleNamespace(backend='native', seconds=10, max_steps=1, seed='TEST',
                               hp=40, max_hp=80, gold=100, policy_config=Path('unused'))
        with tempfile.TemporaryDirectory() as folder, patch.object(checks, 'NativeFixture', Environment), patch.object(checks, 'Mentor', Policy):
            report = checks.one_case(args, {'name': 'Test', 'id': 'EVENT.TEST'}, [], Path(folder), lambda _: None, set())
        self.assertEqual(report['status'], 'fault')
        self.assertEqual(report['exitCode'], 1)

    def test_replay_drift_does_not_spawn_more_paths(self):
        before = self.boundary('event')
        class Environment:
            last = before
            def __init__(self, *args):
                pass
            def begin(self, *args):
                return self.last
            def close(self):
                return {'processReaped': True, 'exitCode': 0}
        class Policy:
            identity = {}
            selection_fallback = False
            def __init__(self, *args):
                self.context = SimpleNamespace(reset=lambda: None)
        args = SimpleNamespace(backend='native', seconds=10, max_steps=1, seed='TEST',
                               hp=40, max_hp=80, gold=100, policy_config=Path('unused'))
        queued = []
        with tempfile.TemporaryDirectory() as folder, patch.object(checks, 'NativeFixture', Environment), patch.object(checks, 'Mentor', Policy):
            report = checks.one_case(args, {'name': 'Test', 'id': 'EVENT.TEST'},
                [{'state': 'stale', 'action_id': 'event:0'}], Path(folder), queued.append, set())
        self.assertEqual(report['status'], 'fault')
        self.assertEqual(queued, [])


if __name__ == '__main__':
    unittest.main()
