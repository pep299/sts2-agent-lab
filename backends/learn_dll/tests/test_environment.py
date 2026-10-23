from pathlib import Path
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from learn_environment import LearnEnvironment

HOST = '''import json
import sys
import time
for line in sys.stdin:
    request = json.loads(line)
    if request['cmd'] == 'close':
        break
    if request.get('seed') == 'SLOW':
        time.sleep(10)
    if request.get('seed') == 'ERROR':
        print(json.dumps({'error': 'unsupported_fixture'}), flush=True)
        continue
    print(json.dumps({'state': {'phase': 'grid_selection', 'terminal': None,
        'selection': {'min': 1, 'max': 2, 'cards': [{}, {}, {}]}},
        'actions': [{'id': 'public:choice', 'detail': {'nativeOptionIndex': 7}},
                    {'id': 'dll:select_cards', 'detail': {'parameter': 'cardIndices'}}],
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
            with self.subTest(indices=indices), self.assertRaises(ValueError):
                self.env.step({'action_id': 'choose_cards:', 'indices': indices})
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
