import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib
import unittest

REPO = Path(__file__).resolve().parents[3]
CONFIG = Path(os.environ.get('MENTOR_CONFIG', REPO / 'config/mentor.example.toml')).resolve()


class PolicyCliContract(unittest.TestCase):
    def test_initialization_and_cli_budget_override_from_another_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, '-B', '-m', 'agents.mentor',
                                     '--config', str(CONFIG), '--sims', '7'],
                                    input='', capture_output=True, text=True, cwd=directory,
                                    env=dict(os.environ, PYTHONPATH=str(REPO)), timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, '')
            info = json.loads(result.stderr)
            config = tomllib.loads(CONFIG.read_text())
            self.assertEqual(info['build_git'], config['identity']['build_git'])
            self.assertEqual(info['search'], config['search'] | {'sims': 7})
            self.assertIn('sts2/selection.py', info['source_sha256'])

    def test_wrong_model_identity_fails_before_accepting_input(self):
        with tempfile.TemporaryDirectory() as directory:
            config = tomllib.loads(CONFIG.read_text())
            invalid = Path(directory) / 'invalid.toml'
            invalid.write_text(CONFIG.read_text().replace(config['identity']['model_sha256'], '0' * 64))
            result = subprocess.run([sys.executable, '-B', '-m', 'agents.mentor',
                                     '--config', str(invalid)], input='', capture_output=True,
                                    text=True, cwd=REPO, timeout=30)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('model hash differs', result.stderr)
