"""固定したMentor拡張・配布モデルと推論設定を読み込む。"""
import hashlib
import importlib.util
from importlib.machinery import ExtensionFileLoader
from pathlib import Path
import sys
import tomllib

REPO = Path(__file__).resolve().parents[2]


def default_config():
    local = REPO / 'config/mentor.local.toml'
    return local if local.is_file() else REPO / 'config/mentor.example.toml'


def asset_path(value):
    path = Path(value).expanduser()
    return path if path.is_absolute() else REPO / path


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class MentorRuntime:
    def __init__(self, configuration):
        config = tomllib.loads(Path(configuration).read_text())
        library = asset_path(config['paths']['extension'])
        model = asset_path(config['paths']['model'])
        expected = config.get('identity', {})
        model_hash = sha(model)
        if 'model_sha256' in expected and model_hash != expected['model_sha256']:
            raise ValueError('Mentor model hash differs from configuration')
        spec = importlib.util.spec_from_file_location('mentor_rs', library,
                    loader=ExtensionFileLoader('mentor_rs', str(library)))
        self.engine = importlib.util.module_from_spec(spec)
        sys.modules['mentor_rs'] = self.engine
        spec.loader.exec_module(self.engine)
        build_git = self.engine.build_git()
        if 'build_git' in expected and build_git != expected['build_git']:
            raise ValueError('Mentor extension build differs from configuration')
        features = expected.get('features', '')
        self.net = self.engine.PpoNetPolicy(str(model), features)
        self.identity = {'build_git': build_git, 'extension_sha256': sha(library),
                         'model_sha256': model_hash, 'features': features}
        self.search = config['search']
        if any(type(self.search.get(k)) is not int or self.search[k] < 1
               for k in ('sims', 'boss_sims', 'threads')):
            raise ValueError('searchのsims・boss_sims・threadsは正の整数を指定')
        self.registries = {kind: set(self.engine.list_registry_names(kind))
                           for kind in ['card', 'power', 'relic', 'potion', 'enchantment', 'orb']}
