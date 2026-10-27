import copy
import importlib.util
from io import StringIO
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

module = importlib.util.spec_from_file_location('fixed_event_checks', Path(__file__).with_name('run.py'))
checks = importlib.util.module_from_spec(module)
module.loader.exec_module(checks)


class FixedCases(unittest.TestCase):
    def setUp(self):
        self.spec = {'name': 'test', 'event': 'Test', 'seed': 'FIXED', 'hp': 6, 'max_hp': 80,
                     'gold': 55, 'fixture': {'act': 2}, 'expect': {
                         'present': [{'key': 'TEST.A'}], 'absent': [{'key': 'TEST.LOCKED'}],
                         'branches': [{'selected': {'key': 'TEST.A'}, 'phases': ['grid_selection'], 'terminal': None}]}}
        self.record = {'event': {'name': 'Test'}, 'status': 'completed',
                       'initialCondition': {'character': 'IRONCLAD', 'ascension': 0, 'seed': 'FIXED',
                                            'hp': 6, 'maxHp': 80, 'gold': 55, 'act': 2},
                       'before': {'hp': 6, 'maxHp': 80, 'gold': 55, 'act': 2},
                       'trace': [self.step('TEST.A'), self.step(None)], 'after': {'terminal': None}}

    def step(self, key, index=0):
        return {'phase': 'event' if key else 'grid_selection',
                'candidates': [{'key': key, 'option_index': index, 'action_id': f'event:{index}'}] if key else [],
                'response': {'action_id': f'event:{index}' if key else 'select'}}

    def test_all_declared_cases_are_loadable_and_names_are_unique(self):
        manifest = json.loads(Path(__file__).with_name('cases.json').read_text())
        names = [row['name'] for row in manifest['cases']]
        self.assertTrue(names)
        self.assertEqual(len(names), len(set(names)))
        for row in manifest['cases']:
            with self.subTest(row['name']):
                self.assertEqual(checks.fixed_case(row['name'])['name'], row['name'])
        with self.assertRaisesRegex(ValueError, '未知'):
            checks.fixed_case('not-a-case')

    def test_typo_empty_expectation_and_fixture_escape_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'cases.json'
            (path.parent / 'fixtures').mkdir()
            (path.parent / 'fixtures/valid.json').write_text('{"act": 2}')
            base = dict(self.spec, fixture='fixtures/valid.json')
            for change in ({'golds': 100}, {'expect': {'branches': []}}, {'fixture': '../elsewhere.json'},
                           {'expect': {'branches': [{'selected': {'key': 'A'}, 'phase': [], 'terminal': None}]}}):
                with self.subTest(change):
                    path.write_text(json.dumps({'defaults': {}, 'cases': [base | change]}))
                    with self.assertRaises(ValueError):
                        checks.fixed_case('test', path)

    def test_exact_branch_and_subsequent_child_phase_pass(self):
        self.assertEqual(checks.check_expectations(self.spec, [self.record]), [])

    def test_missing_branch_does_not_pass_merely_by_completion(self):
        self.record['trace'][0] = self.step('TEST.OTHER')
        self.assertTrue(checks.check_expectations(self.spec, [self.record]))

    def test_child_phase_from_another_event_selection_cannot_satisfy_branch(self):
        self.record['trace'] = [self.step('TEST.A'), self.step('TEST.B'), self.step(None)]
        missing = checks.check_expectations(self.spec, [self.record])
        self.assertIn({'branch': self.spec['expect']['branches'][0]}, missing)

    def test_child_phase_before_selection_cannot_satisfy_branch(self):
        self.record['trace'] = [self.step(None), self.step('TEST.A')]
        self.assertTrue(checks.check_expectations(self.spec, [self.record]))

    def test_terminal_fault_and_declared_or_observed_condition_mismatch_fail(self):
        changes = [('status', 'fault'), ('after', {'terminal': 'death'}),
                   ('initialCondition', self.record['initialCondition'] | {'seed': 'OTHER'}),
                   ('event', {'name': 'Other'})]
        changes += [('before', self.record['before'] | {key: value})
                    for key, value in (('hp', 7), ('maxHp', 81), ('gold', 54), ('act', 1))]
        for key, value in changes:
            with self.subTest(key=key, value=value):
                changed = copy.deepcopy(self.record)
                changed[key] = value
                self.assertTrue(checks.check_expectations(self.spec, [changed]))
        self.assertTrue(checks.check_expectations(self.spec, []))

    def test_initial_presence_and_absence_are_independent_of_selected_branch(self):
        self.record['trace'][0]['candidates'].append({'key': 'TEST.LOCKED', 'action_id': 'event:1'})
        self.assertIn({'absent': {'key': 'TEST.LOCKED'}}, checks.check_expectations(self.spec, [self.record]))

    def test_duplicate_public_key_requires_slot_to_prove_selection(self):
        self.record['trace'][0]['candidates'].append({'key': 'TEST.A', 'option_index': 1, 'action_id': 'event:1'})
        self.assertTrue(checks.check_expectations(self.spec, [self.record]))
        self.spec['expect']['present'][0]['option_index'] = 0
        self.spec['expect']['branches'][0]['selected']['option_index'] = 0
        self.assertEqual(checks.check_expectations(self.spec, [self.record]), [])

    def invoke(self, arguments, result):
        with patch.object(checks.sys, 'argv', ['run.py', '--backend', 'native', '--output', 'local/unused'] + arguments), \
                patch.object(checks, 'run', return_value=result) as run, patch.object(checks.sys, 'stderr', StringIO()), \
                self.assertRaises(SystemExit) as exit_result:
            checks.main()
        return exit_result.exception.code, run

    def test_fixed_case_conditions_cannot_be_overridden(self):
        for override in (['--hp', '7'], ['--gold', '1'], ['--seed', 'OTHER'], ['--fixture', 'other.json'], ['--max-hp', '81']):
            with self.subTest(override):
                code, run = self.invoke(['--case', 'stone-hp6'] + override, {'cases': []})
                self.assertEqual(code, 2)
                run.assert_not_called()

    def test_fixed_case_expands_conditions_and_ordinary_events_keep_defaults(self):
        ok = {'cases': [{'status': 'completed'}]}
        code, run = self.invoke(['--case', 'stone-hp6'], ok)
        args = run.call_args.args[0]
        self.assertEqual((code, args.events, args.hp, args.fixture),
                         (0, ['StoneOfAllTime'], 6, {'act': 2, 'potions': ['FIRE_POTION']}))
        code, run = self.invoke(['--events', 'StoneOfAllTime'], ok)
        args = run.call_args.args[0]
        self.assertEqual((code, args.hp, args.max_hp, args.gold, args.seed, args.fixture),
                         (0, 40, 80, 100, 'EVENTCOVER111', {}))

    def test_completed_execution_with_missing_expectation_exits_one(self):
        code, _ = self.invoke(['--case', 'stone-hp6'], {
            'cases': [{'status': 'completed'}], 'regression': {'passed': False, 'missing': ['branch']}})
        self.assertEqual(code, 1)
        self.assertFalse(checks.succeeded({'cases': []}))

    def test_run_preserves_execution_status_and_reports_unvisited_expectation(self):
        spec = checks.fixed_case('stone-hp6')
        record = copy.deepcopy(self.record)
        record.update(event={'name': 'StoneOfAllTime'}, initialCondition={
            'character': 'IRONCLAD', 'ascension': 0, 'seed': spec['seed'],
            'hp': spec['hp'], 'maxHp': spec['max_hp'], 'gold': spec['gold'], **spec['fixture']},
            before={'hp': 6, 'maxHp': 80, 'gold': 100, 'act': 2}, mentorDecisions=1, forcedDecisions=0)
        record['trace'][0] = self.step('STONE_OF_ALL_TIME.pages.INITIAL.options.LIFT')
        record['trace'][0]['candidates'].append({
            'key': 'STONE_OF_ALL_TIME.pages.INITIAL.options.PUSH', 'action_id': 'event:1'})
        def completed(args, event, prefix, output, schedule, executed):
            output.mkdir(parents=True)
            checks.write(output / 'case.json', record)
            return record
        with tempfile.TemporaryDirectory() as directory:
            args = SimpleNamespace(catalog=Path(__file__).with_name('catalog.json'), events=['StoneOfAllTime'],
                output=Path(directory) / 'local/out', backend='learn', max_paths=64, case_spec=spec)
            with patch.object(checks, 'REPO', Path(directory).resolve()), \
                    patch.object(checks, 'one_case', completed), patch('builtins.print'):
                summary = checks.run(args)
            saved = json.loads((args.output / 'summary.json').read_text())
        self.assertEqual(summary['cases'][0]['status'], 'completed')
        self.assertFalse(summary['regression']['passed'])
        self.assertTrue(summary['regression']['missing'])
        self.assertEqual(saved, summary)
        self.assertFalse(checks.succeeded(summary))


if __name__ == '__main__':
    unittest.main()
