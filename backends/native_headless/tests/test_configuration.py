from pathlib import Path
import os
import tempfile
import unittest
from unittest.mock import patch

from configuration import ConfigurationError, REPO, TEMPLATE, load_config, resolve_path
from runtime import NativeEnvironment,EnvironmentFault,validate_mods


class ConfigurationTests(unittest.TestCase):
    def test_unrelated_mod_cannot_be_treated_as_the_qualified_runtime(self):
        for relative in ['other-mod/extra.json','spire-jev-bridge/nested/extra.json','.hidden/extra.json']:
            with self.subTest(relative=relative),tempfile.TemporaryDirectory() as directory:
                executable=Path(directory)/'game'
                mods=Path(directory)/'mods';(mods/'spire-jev-bridge').mkdir(parents=True)
                (mods/'spire-jev-bridge/spire-jev-bridge.json').write_text('{}')
                validate_mods(executable)
                extra=mods/relative;extra.parent.mkdir(parents=True,exist_ok=True);extra.write_text('{}')
                with self.assertRaisesRegex(EnvironmentFault,'unqualified_mods:'):
                    validate_mods(executable)

    def test_linked_mod_directories_are_rejected_without_following_them(self):
        for relative in ['mods','mods/linked-mod','mods/spire-jev-bridge/linked-mod']:
            with self.subTest(relative=relative),tempfile.TemporaryDirectory() as directory:
                root=Path(directory);source=root/'source';source.mkdir()
                (source/'extra.json').write_text('{}')
                link=root/relative;link.parent.mkdir(parents=True,exist_ok=True)
                link.symlink_to(source,target_is_directory=True)
                with self.assertRaisesRegex(EnvironmentFault,'unqualified_mods:'):
                    validate_mods(root/'game')

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
