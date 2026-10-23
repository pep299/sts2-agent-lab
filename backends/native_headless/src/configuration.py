"""追跡するテンプレートと、追跡しない実行設定・資産の境界。"""
from pathlib import Path
import os
import shutil
import tomllib

REPO = Path(__file__).resolve().parents[3]
BACKEND = Path(__file__).resolve().parents[1]
TEMPLATE = REPO / 'config/native-headless.example.toml'

class ConfigurationError(ValueError):
    pass

def config_file():
    value = Path(os.environ.get('STS2_NATIVE_CONFIG', REPO / 'config/native-headless.local.toml'))
    return (REPO / value).resolve() if not value.is_absolute() else value.resolve()

def resolve_path(value):
    path = Path(value).expanduser()
    return (REPO / path).resolve() if not path.is_absolute() else path.resolve()

def load_config(*, required=True):
    path = config_file()
    if not path.is_file():
        if required:
            raise ConfigurationError('Copy config/native-headless.example.toml to config/native-headless.local.toml and provide local inputs')
        path = TEMPLATE
    data = tomllib.loads(path.read_text())
    if data.get('schema_version') != 1:
        raise ConfigurationError('Unsupported native configuration schema')
    required_paths = {'local_root', 'source_app', 'progress', 'settings', 'dotnet'}
    if set(data['paths']) != required_paths:
        raise ConfigurationError('Native paths must contain exactly: ' + ', '.join(sorted(required_paths)))
    if not resolve_path(data['paths']['local_root']).is_relative_to(REPO / 'local'):
        raise ConfigurationError('local_root must resolve inside the ignored repository local/ directory')
    return data

def dotnet_command():
    value = load_config()['paths']['dotnet']
    executable = resolve_path(value) if '/' in value else shutil.which(value)
    if not executable or not Path(executable).is_file():
        raise ConfigurationError('Configured dotnet executable is unavailable')
    return str(executable)

LOCAL = resolve_path(load_config(required=False)['paths']['local_root'])
RESULTS = LOCAL / 'results'
PROFILE_TEMPLATE = LOCAL / 'profile-template'
EPISODES = LOCAL / 'episodes'
BUILD = LOCAL / 'build'
MANIFEST = LOCAL / 'runtime-manifest.json'
LOCK = LOCAL / 'runtime.lock'
