import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from mentor_chat import Session


class SessionTests(unittest.TestCase):
    def start(self):
        return Session.start(seed=7)

    def enter_combat(self, session):
        for _ in range(20):
            phase = session.rm.phase()
            if phase == "combat":
                return
            actions = session.observe()["actions"]
            if phase == "map_choice":
                moves = [a for a in actions if a["action"] == "move"]
                session.act(min(moves, key=lambda a: a["col"]))
            else:
                session.act(actions[0])
        self.fail("最初の戦闘まで進行しませんでした")

    def test_opening_map_and_choices_do_not_advance(self):
        session = Session.start()
        before = session.rm.rng_counters()
        view = session.observe()
        self.assertEqual(view["game_version"], "v0.113.0")
        self.assertEqual(session.rm.character, "Ironclad")
        self.assertEqual(session.rm.ascension_level, 10)
        self.assertEqual(view["run_hp"], session.rm.current_hp)
        self.assertEqual(view["gold"], session.rm.gold)
        self.assertEqual(view["phase"], "event")
        self.assertEqual(len(view["neow_offers"]), 3)
        self.assertEqual(len(view["event_options"]), 3)
        self.assertTrue(all(option["description"] for option in view["event_options"]))
        self.assertTrue(session.rm.act_map())
        self.assertEqual(session.history, [])
        self.assertEqual(before, session.rm.rng_counters())

    def test_random_seed_is_saved_and_reused(self):
        session = Session.start()
        seed = session.config["seed"]
        self.assertIs(type(seed), int)
        self.assertTrue(0 <= seed < 2 ** 31)
        with tempfile.TemporaryDirectory() as directory:
            saved = Path(directory) / "run.json"
            session.save(saved)
            restored = Session.load(saved)
        self.assertEqual(restored.config["seed"], seed)
        self.assertEqual(restored.observe(), session.observe())
        self.assertEqual(session.fork(0).config["seed"], seed)

    def test_explicit_start_parameters_are_used(self):
        session = Session.start(character="Silent", ascension_level=5, seed=7)
        self.assertEqual(session.rm.character, "Silent")
        self.assertEqual(session.rm.ascension_level, 5)
        self.assertEqual(session.config["seed"], 7)
        self.assertEqual(session.observe()["game_version"], "v0.113.0")

    def test_combat_trace_fork_and_fresh_process_restore(self):
        session = self.start()
        self.enter_combat(session)
        before = session.observe()
        before_steps = len(session.history)
        record = session.act({"action": "end_turn"})
        self.assertTrue(record["before"]["combat"]["hand"])
        self.assertTrue(record["before"]["combat"]["enemies"])
        self.assertTrue(record["combat_log"])
        self.assertEqual(record["combat_log_dropped"], 0)

        branch = session.fork(before_steps)
        self.assertEqual(branch.observe(), before)
        self.assertEqual(branch.act({"action": "end_turn"}), record)
        self.assertEqual(len(session.history), before_steps + 1)
        branch.act({"action": "end_turn"})
        self.assertEqual(session.observe(), record["after"])
        self.assertEqual(len(branch.history), before_steps + 2)

        with tempfile.TemporaryDirectory() as directory:
            saved = Path(directory) / "run.json"
            session.save(saved)
            script = """
import json, sys
from mentor_chat import Session
s = Session.load(sys.argv[1])
print(json.dumps({'steps': len(s.history), 'view': s.observe(),
                  'config': s.config, 'rng': s.rm.rng_counters()}, sort_keys=True))
"""
            restored = json.loads(subprocess.check_output(
                [sys.executable, "-c", script, str(saved)], text=True))
            expected = dict(steps=len(session.history), view=session.observe(),
                            config=session.config, rng=session.rm.rng_counters())
            self.assertEqual(restored, json.loads(json.dumps(expected)))

    def test_reports_engine_action_failure(self):
        session = self.start()
        with self.assertRaises(RuntimeError):
            session.act({"action": "end_turn"})
        self.assertEqual(session.history, [])


if __name__ == "__main__":
    unittest.main()
