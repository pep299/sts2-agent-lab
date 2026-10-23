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
    def test_each_backend_initializes_pinned_assets_from_another_directory(self):
        for backend in ['native', 'learn']:
            with self.subTest(backend=backend), tempfile.TemporaryDirectory() as directory:
                result = subprocess.run([sys.executable, '-B', str(REPO / 'agents/mentor/policy.py'),
                                         '--config', str(CONFIG), '--backend', backend, '--sims', '7'],
                                        input='', capture_output=True, text=True, cwd=directory, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, '')
                info = json.loads(result.stderr)
                config = tomllib.loads(CONFIG.read_text())
                self.assertEqual(info['build_git'], config['identity']['build_git'])
                self.assertEqual(info['search'], config['search'] | {'sims': 7})
                self.assertEqual('learn_observation.py' in info['source_sha256'], backend == 'learn')
