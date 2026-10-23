from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[2]


class RunnerEntries(unittest.TestCase):
    def test_native_help_needs_no_model_build_or_game_launch(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, '-B', str(REPO / 'runners/mentor_native.py'), '--help'],
                                    cwd=directory, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--seed', result.stdout)

    def test_learn_help_needs_no_model_build_or_game_launch(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, '-B', str(REPO / 'runners/mentor_learn.py'), '--help'],
                                    cwd=directory, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--seed', result.stdout)
