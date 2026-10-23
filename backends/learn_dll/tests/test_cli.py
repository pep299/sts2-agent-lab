from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from backends.learn_dll import batch


class LearnCliContract(unittest.TestCase):
    def test_help_from_another_directory_needs_no_host_or_mentor(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, '-B', '-m', 'backends.learn_dll.batch', '--help'],
                                    cwd=directory, capture_output=True, text=True, timeout=10,
                                    env=dict(os.environ, PYTHONPATH=str(batch.REPO)))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--policy-cwd', result.stdout)
        self.assertIn('--policy-command', result.stdout)

    def test_cli_passes_default_or_explicit_policy_cwd(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for cwd in (None, root):
                with self.subTest(cwd=cwd):
                    argv = ['batch', '--dotnet', sys.executable, '--seed', 'EXAMPLE',
                            '--output', str(root / 'result')]
                    if cwd is not None:
                        argv += ['--policy-cwd', str(cwd)]
                    command = [sys.executable, '-m', 'a_policy']
                    argv += ['--policy-command', *command]
                    with patch.object(sys, 'argv', argv), \
                            patch.object(batch, 'run_episode', return_value={'outcome': 'completed'}) as run, \
                            redirect_stdout(StringIO()) as output, self.assertRaises(SystemExit) as exit_result:
                        batch.main()
                    self.assertEqual(exit_result.exception.code, 0)
                    self.assertEqual(run.call_args.kwargs['policy_cwd'], cwd or batch.REPO)
                    self.assertEqual(run.call_args.args[4], command)
                    self.assertEqual(json.loads(output.getvalue()), {'outcome': 'completed'})
