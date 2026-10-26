from pathlib import Path
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from backends.learn_dll.learn_environment import LearnEnvironment
from backends.common.policy_io import PolicyFault

HOST = '''import json
import sys
import time
from pathlib import Path
log = Path(sys.argv[sys.argv.index('--log') + 1]).open('x')
run_seed = None
for line in sys.stdin:
    request = json.loads(line)
    log.write(json.dumps(request) + '\\n')
    log.flush()
    if request['cmd'] == 'reset':
        run_seed = request['seed']
    if request['cmd'] == 'close':
        break
    if request.get('seed') == 'SLOW':
        time.sleep(10)
    if request.get('seed') == 'ERROR':
        print(json.dumps({'error': 'unsupported_fixture'}), flush=True)
        continue
    print(json.dumps({'state': {'phase': 'grid_selection', 'terminal': 'victory' if run_seed == 'COMPLETE' and request['cmd'] == 'step' else None,
        'status': {'map': None, 'act': 1, 'floor': 0, 'hp': 80, 'maxHp': 80},
        'selection': {'min': 1, 'max': 2, 'cards': [{}, {}, {}]}},
        'actions': [{'id': 'public:choice', 'detail': {'nativeKind': 'EndTurn', 'nativeOptionIndex': 7}},
                    {'id': 'dll:select_cards', 'detail': {'nativeKind': 'SelectCards', 'parameter': 'cardIndices'}}],
        'received': request}), flush=True)
'''


class LearnEnvironmentContract(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        host = self.root / 'addons/public-observation/Sts2DllRecorder/bin/Release/net9.0/Sts2DllRecorder.dll'
        host.parent.mkdir(parents=True)
        host.write_text(HOST)
        self.env = LearnEnvironment(self.root, sys.executable, self.root / 'output', timeout=1)
        self.addCleanup(self.env.close)

    def test_action_uses_native_option_index_instead_of_array_position(self):
        initial = self.env.reset('EXAMPLE')
        self.assertEqual(initial['decision_id'], 1)
        self.assertEqual(initial['observation']['received']['actGeneration'], 'seeded_all_unlocked')
        result = self.env.step({'action_id': 'public:choice'})
        self.assertEqual(result['observation']['received'], {'cmd': 'step', 'index': 7})
        self.assertEqual((result['decision_id'], self.env.steps), (2, 1))

    def test_parameterized_selection_keeps_the_complete_set(self):
        self.env.reset('EXAMPLE')
        result = self.env.step({'action_id': 'choose_cards:', 'indices': [2, 0]})
        self.assertEqual(result['observation']['received'], {'cmd': 'step', 'cardIndices': [2, 0]})

    def test_invalid_selection_never_reaches_host(self):
        self.env.reset('EXAMPLE')
        for indices in [[], [0, 0], [3], [-1], [True], [0, 1, 2]]:
            with self.subTest(indices=indices), self.assertRaises(PolicyFault):
                self.env.step({'action_id': 'choose_cards:', 'indices': indices})
        self.assertEqual((self.env.decision_id, self.env.steps), (1, 0))

    def test_unknown_action_is_a_policy_fault_without_advancing_host(self):
        self.env.reset('EXAMPLE')
        with self.assertRaisesRegex(PolicyFault, '行動IDが公開候補にない'):
            self.env.step({'action_id': 'not_a_candidate'})
        self.assertEqual((self.env.decision_id, self.env.steps), (1, 0))

    def test_hidden_native_selection_ids_never_reach_host(self):
        self.env.reset('EXAMPLE')
        for decision in ({'action_id': 'dll:select_cards'},
                         {'action_id': 'dll:select_cards', 'indices': [0]},
                         {'action_id': 'choose_cards:'}):
            with self.subTest(decision=decision), self.assertRaises(PolicyFault):
                self.env.step(decision)
        self.assertEqual((self.env.decision_id, self.env.steps), (1, 0))

    def test_host_fault_cannot_become_a_terminal_loss(self):
        with self.assertRaisesRegex(RuntimeError, 'unsupported_fixture'):
            self.env.reset('ERROR')
        self.assertIsNone(self.env.last)
        self.assertEqual(self.env.steps, 0)

    def test_read_deadline_and_close_reap_host(self):
        self.env.reset('EXAMPLE')
        with self.assertRaises(TimeoutError):
            self.env.reset('SLOW', deadline=time.monotonic() + .03)
        self.env.close()
        self.assertIsNotNone(self.env.process.poll())

    def test_missing_host_does_not_create_output(self):
        output = self.root / 'missing-output'
        with self.assertRaises(FileNotFoundError):
            LearnEnvironment(self.root / 'missing-root', sys.executable, output)
        self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
