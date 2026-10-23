from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from backends.learn_dll.batch import REPO, run_episode
from test_environment import HOST

POLICY = "import sys,json\nfor line in sys.stdin:\n print(json.dumps({'action_id':'choose_cards:','indices':[0]}),flush=True)\n"


class BackendBatchContract(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        host = self.root / 'addons/public-observation/Sts2DllRecorder/bin/Release/net9.0/Sts2DllRecorder.dll'
        host.parent.mkdir(parents=True)
        host.write_text(HOST)
        results = REPO / 'local/learn_dll/results'
        results.mkdir(parents=True, exist_ok=True)
        self.output_parent = tempfile.TemporaryDirectory(dir=results)
        self.addCleanup(self.output_parent.cleanup)

    def run_policy(self, command, seed, **limits):
        output = Path(self.output_parent.name) / 'run'
        # ホストはlearnのcheckoutではなく、ローカルの通信フィクスチャ。
        with patch('backends.learn_dll.batch.subprocess.check_output', side_effect=['fixture\n', '']), redirect_stdout(StringIO()):
            report = run_episode(self.root, sys.executable, output, seed, command, **limits)
        self.assertEqual(json.loads((output / 'result.json').read_text()), report)
        self.assertTrue(report['processReaped'])
        return report

    def test_non_mentor_policy_can_complete_without_model_or_rust(self):
        report = self.run_policy([sys.executable, '-u', '-c', POLICY], 'COMPLETE')
        self.assertEqual((report['outcome'], report['terminal'], report['dataValid'], report['steps']),
                         ('completed', 'victory', True, 1))

    def test_policy_failure_is_not_a_game_loss(self):
        report = self.run_policy([sys.executable, '-c', 'print("invalid-json")'], 'EXAMPLE')
        self.assertEqual((report['outcome'], report['terminal'], report['dataValid'], report['faultOwner']),
                         ('fault', None, False, 'policy'))

    def test_step_budget_is_interruption_instead_of_failure(self):
        report = self.run_policy([sys.executable, '-u', '-c', POLICY], 'EXAMPLE', max_steps=1)
        self.assertEqual((report['outcome'], report['terminal'], report['dataValid']), ('interrupted', None, False))
