from pathlib import Path
import os
import tempfile
import unittest
from unittest.mock import patch

from configuration import ConfigurationError, REPO, TEMPLATE, load_config, resolve_path
from runtime import NativeEnvironment


class ConfigurationTests(unittest.TestCase):
    def test_missing_real_configuration_cannot_start_or_create_output(self):
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory)/'output'
            with patch.dict(os.environ,{'STS2_NATIVE_CONFIG':str(Path(directory)/'missing.toml')}):
                with self.assertRaisesRegex(ConfigurationError,'Copy config/'):
                    NativeEnvironment(output,'CONFIGTEST')
            self.assertFalse(output.exists())

    def test_assets_cannot_be_directed_into_tracked_source(self):
        with tempfile.TemporaryDirectory() as directory:
            config=Path(directory)/'local.toml'
            config.write_text(TEMPLATE.read_text().replace('local_root = "local/native_headless"',
                                                           'local_root = "backends/native_headless/mod"'))
            with patch.dict(os.environ,{'STS2_NATIVE_CONFIG':str(config)}):
                with self.assertRaisesRegex(ConfigurationError,'ignored repository local/'):
                    load_config()

    def test_relative_inputs_resolve_from_repository_not_caller_directory(self):
        previous=Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            try:
                os.chdir(directory)
                self.assertEqual(resolve_path('local/native_headless/data/progress.save'),
                                 REPO/'local/native_headless/data/progress.save')
            finally:os.chdir(previous)


if __name__=='__main__':unittest.main()
