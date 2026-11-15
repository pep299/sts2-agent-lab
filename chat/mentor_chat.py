"""Mentorの行動記録と、同じバイナリによる再生。ゲームルールはMentorが処理する。"""

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from secrets import randbits


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value):
    return sha256(_json(value).encode()).hexdigest()


class Session:
    def __init__(self, config):
        import sts2_rs

        if not config.get("game_version"):
            raise ValueError("game_versionを明示してください。未対応版への自動フォールバックはしません")
        self.engine = sts2_rs
        self.config = deepcopy(config)
        self.rm = sts2_rs.RunManager(**self.config)
        self.rm.set_record_card_plays(True)
        self.rm.set_record_combat_log(True)
        self._prepare(self.rm)
        self.history = []
        self.origin = None
        self.identity = {
            "extension_sha256": sha256(Path(sts2_rs.__file__).read_bytes()).hexdigest(),
            "helper_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
        }
        manifest = Path(__file__).with_name("manifest.json")
        self.manifest = json.loads(manifest.read_text()) if manifest.exists() else None
        if self.manifest:
            for name, expected in self.manifest["files"].items():
                actual = sha256((manifest.parent / name).read_bytes()).hexdigest()
                if actual != expected:
                    raise ValueError(f"artifactのファイルがmanifestと一致しません: {name}")
            if self.identity["extension_sha256"] != self.manifest["files"]["sts2_rs.abi3.so"]:
                raise ValueError("読み込み済みのsts2_rsがこのartifactと異なります。実行環境を再起動してください")
        self.initial_check = self._check(self.rm)

    @classmethod
    def start(cls, *, game_version="v0.113.0", seed=None, character="Ironclad", ascension_level=10,
              act1="roll"):
        if seed is None:
            seed = randbits(31)
        config = dict(game_version=game_version, character=character,
                      ascension_level=ascension_level, act1=act1, neow_start=True,
                      mode="agent", interactive_potion_swap=True)
        config["string_seed" if isinstance(seed, str) else "seed"] = seed
        return cls(config)

    @staticmethod
    def _prepare(rm):
        if rm.phase() == "event":
            rm.materialize_event()

    def _view(self, rm):
        cs = rm.combat_state()
        return dict(
            game_version=rm.game_version, phase=rm.phase(), act=rm.act_index,
            floor=rm.act_floor(), total_floor=rm.total_floor(),
            run_hp=rm.current_hp, run_max_hp=rm.max_hp, gold=rm.gold,
            potions=rm.potions(), relics=rm.relics(),
            deck=rm.master_deck_detailed(), enchantments=rm.master_deck_enchantments(),
            map_coord=rm.map_coord(), actions=rm.available_actions(),
            neow_offers=rm.neow_offers(), event=rm.current_event_name(),
            event_options=rm.event_option_infos(), rest_options=rm.rest_site_options(),
            card_reward=rm.card_reward_options(), shop=rm.shop_inventory(),
            combat=cs.get_state() if cs is not None and rm.phase() == "combat" else None,
        )

    def _check(self, rm):
        cs = rm.combat_state()
        return _digest(dict(view=self._view(rm), rng=rm.rng_counters(),
                            map=rm.act_map(),
                            combat=self.engine.state_to_dict(cs) if cs is not None else None,
                            log=rm.combat_log(), dropped=rm.combat_log_dropped()))

    def observe(self):
        return deepcopy(self._view(self.rm))

    def act(self, action):
        self._assert_recorded()
        action = json.loads(_json(action))
        before = self.observe()
        # 失敗した処理が途中まで状態を変えても、採用中の分岐には反映しない。
        candidate = self.rm.clone()
        result = candidate.take_action(action)
        if result not in {"advanced", "run_over"}:
            raise RuntimeError(f"Mentorが行動を完了しませんでした: {result}: {action}")
        self._prepare(candidate)
        record = dict(action=action, result=result, before=before,
                      after=self._view(candidate), check=self._check(candidate),
                      combat_log=candidate.combat_log(),
                      combat_log_dropped=candidate.combat_log_dropped())
        self.rm = candidate
        self.history.append(record)
        return deepcopy(record)

    def save(self, path):
        self._assert_recorded()
        data = dict(format="mentor-chat-replay-v1", identity=self.identity,
                    manifest=self.manifest, config=self.config,
                    initial_check=self.initial_check, origin=self.origin,
                    history=self.history)
        path = Path(path)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        temporary.replace(path)

    def _assert_recorded(self):
        if self._check(self.rm) != (self.history[-1]["check"] if self.history else self.initial_check):
            raise RuntimeError("履歴外の状態変更があります。rmの変更ではなくSession.actを使ってください")

    @classmethod
    def load(cls, path):
        data = json.loads(Path(path).read_text())
        if data["format"] != "mentor-chat-replay-v1":
            raise ValueError("未対応の保存形式です")
        session = cls(data["config"])
        if session.identity != data["identity"]:
            raise ValueError("保存時と異なる拡張または補助スクリプトです。元のartifactで再開してください")
        if session.initial_check != data["initial_check"]:
            raise ValueError("開始状態が再現しません")
        for index, saved in enumerate(data["history"]):
            actual = session.act(saved["action"])
            if _json(actual) != _json(saved):
                raise ValueError(f"行動{index + 1}で再生結果が分岐しました")
        session.origin = data["origin"]
        return session

    def fork(self, after_steps):
        self._assert_recorded()
        if type(after_steps) is not int or not 0 <= after_steps <= len(self.history):
            raise ValueError("after_stepsは0から現在の行動数までの整数です")
        branch = type(self)(self.config)
        if branch.initial_check != self.initial_check:
            raise ValueError("分岐の開始状態が再現しません")
        for saved in self.history[:after_steps]:
            if _json(branch.act(saved["action"])) != _json(saved):
                raise ValueError("分岐元までの行動が再現しません")
        branch.origin = dict(after_steps=after_steps, parent_steps=len(self.history),
                             parent_check=self._check(self.rm))
        return branch
