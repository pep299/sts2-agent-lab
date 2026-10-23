"""汎用入口で、方策の作業ディレクトリと出力先を維持する。"""
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch

import batch


class BatchCliContract(unittest.TestCase):
    def test_policy_cwd_and_new_output_parent_without_game_launch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            plan = root / 'plan.json'
            plan.write_text('[]')
            command = [sys.executable, '-B', '-c',
                       'import json, os, sys; '
                       '[(print(json.dumps({"action_id": os.getcwd()}), flush=True)) for line in sys.stdin]']
            for explicit_cwd in (None, root):
                with self.subTest(cwd=explicit_cwd):
                    output = root / ('explicit' if explicit_cwd else 'default') / 'batch'
                    argv = ['batch.py', '--plan', str(plan), '--output', str(output)]
                    if explicit_cwd:
                        argv += ['--policy-cwd', str(explicit_cwd)]
                    argv += ['--policy-command', *command]

                    def exercise_policy(specs, destination, choose):
                        self.assertEqual(specs, [])
                        self.assertTrue(destination.parent.is_dir())
                        decision = choose({'decision_id': 1})
                        self.assertEqual(Path(decision['action_id']), explicit_cwd or batch.REPO)
                        return {'processed': 0}

                    with patch.object(batch, 'RESULTS', root), patch.object(sys, 'argv', argv), \
                            patch.object(batch, 'run_batch', side_effect=exercise_policy), \
                            redirect_stdout(StringIO()) as result:
                        batch.main()
                    self.assertEqual(json.loads(result.getvalue()), {'processed': 0})
                    self.assertTrue(output.with_suffix('.policy-stderr.log').is_file())

    def test_invalid_output_is_rejected_before_policy_start(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            plan = root / 'plan.json'
            plan.write_text('[]')
            argv = ['batch.py', '--plan', str(plan), '--output', str(root / 'outside'),
                    '--policy-command', sys.executable]
            with patch.object(batch, 'RESULTS', root / 'allowed'), patch.object(sys, 'argv', argv), \
                    patch.object(batch, 'JsonLinePolicy') as worker, redirect_stderr(StringIO()):
                with self.assertRaises(SystemExit):
                    batch.main()
                worker.assert_not_called()
