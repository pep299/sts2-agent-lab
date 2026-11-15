"""Mentorの行動記録と、同じバイナリによる再生。ゲームルールはMentorが処理する。"""

from copy import deepcopy
import json
from pathlib import Path
from secrets import randbits


class Session:
    def __init__(self, config):
        import sts2_rs

        self.config = dict(config)
        self.rm = sts2_rs.RunManager(**self.config)
        self.rm.set_record_card_plays(True)
        self.rm.set_record_combat_log(True)
        self._prepare(self.rm)
        self.history = []

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

    def observe(self):
        rm = self.rm
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

    def act(self, action):
        action = deepcopy(action)
        before = self.observe()
        result = self.rm.take_action(action)
        if result not in {"advanced", "run_over"}:
            raise RuntimeError(f"Mentorが行動を完了しませんでした: {result}: {action}")
        self._prepare(self.rm)
        record = dict(action=action, result=result, before=before,
                      after=self.observe(), combat_log=self.rm.combat_log(),
                      combat_log_dropped=self.rm.combat_log_dropped())
        self.history.append(record)
        return deepcopy(record)

    def save(self, path):
        data = dict(config=self.config, actions=[r["action"] for r in self.history])
        Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")

    @classmethod
    def load(cls, path):
        data = json.loads(Path(path).read_text())
        session = cls(data["config"])
        for action in data["actions"]:
            session.act(action)
        return session

    def fork(self, after_steps):
        if not 0 <= after_steps <= len(self.history):
            raise ValueError("after_stepsは0から現在の行動数までです")
        branch = type(self)(self.config)
        for saved in self.history[:after_steps]:
            branch.act(saved["action"])
        return branch
