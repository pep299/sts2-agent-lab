import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from mentor_chat import Session


class SessionTests(unittest.TestCase):
    def start(self):
        return Session.start(game_version="v0.111.0", seed=7)

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
        session = self.start()
        before = session._check(session.rm)
        view = session.observe()
        self.assertEqual(view["phase"], "event")
        self.assertEqual(len(view["neow_offers"]), 3)
        self.assertEqual(len(view["event_options"]), 3)
        self.assertTrue(session.rm.act_map())
        self.assertEqual(session.history, [])
        self.assertEqual(before, session._check(session.rm))

    def test_random_seed_is_saved_and_reused(self):
        session = Session.start(game_version="v0.111.0")
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
        session = Session.start(game_version="v0.111.0", character="Silent",
                                ascension_level=5, seed=7)
        self.assertEqual(session.rm.character, "Silent")
        self.assertEqual(session.rm.ascension_level, 5)
        self.assertEqual(session.config["seed"], 7)
        self.assertEqual(session.observe()["game_version"], "v0.111.0")

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
        self.assertNotEqual(branch._check(branch.rm), session._check(session.rm))
        self.assertLess(branch.observe()["combat"]["player"]["hp"],
                        branch.observe()["run_hp"])

        with tempfile.TemporaryDirectory() as directory:
            saved = Path(directory) / "run.json"
            session.save(saved)
            # 同一プロセス内のcloneだけで再開確認を済ませない。
            script = """
import json, sys
from mentor_chat import Session
s = Session.load(sys.argv[1])
print(json.dumps({'steps': len(s.history), 'view': s.observe(),
                  'check': s._check(s.rm), 'rng': s.rm.rng_counters()}, sort_keys=True))
"""
            restored = json.loads(subprocess.check_output(
                [sys.executable, "-c", script, str(saved)], text=True))
            expected = dict(steps=len(session.history), view=session.observe(),
                            check=session._check(session.rm), rng=session.rm.rng_counters())
            self.assertEqual(restored, json.loads(json.dumps(expected)))

    def test_failed_action_keeps_active_branch(self):
        session = self.start()
        before = session._check(session.rm)
        with self.assertRaises(RuntimeError):
            session.act({"action": "end_turn"})
        self.assertEqual(session._check(session.rm), before)
        self.assertEqual(session.history, [])

    def test_rejects_changed_binary_or_replay(self):
        session = self.start()
        session.act(session.observe()["actions"][0])
        with tempfile.TemporaryDirectory() as directory:
            saved = Path(directory) / "run.json"
            session.save(saved)
            original = json.loads(saved.read_text())
            data = json.loads(saved.read_text())
            data["identity"]["extension_sha256"] = "wrong"
            saved.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, "異なる拡張"):
                Session.load(saved)
            original["history"][0]["check"] = "wrong"
            saved.write_text(json.dumps(original))
            with self.assertRaisesRegex(ValueError, "行動1"):
                Session.load(saved)

    def test_unrecorded_mutation_is_not_saved_or_adopted(self):
        session = self.start()
        session.rm.set_player(gold=999)
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, "履歴外"):
                session.save(Path(directory) / "run.json")
        with self.assertRaisesRegex(RuntimeError, "履歴外"):
            session.act(session.observe()["actions"][0])

    def test_version_required_and_fork_bounds(self):
        with self.assertRaisesRegex(ValueError, "game_version"):
            Session({"seed": 7})
        session = self.start()
        for invalid in (-1, 1, True):
            with self.subTest(after_steps=invalid):
                with self.assertRaises(ValueError):
                    session.fork(invalid)


if __name__ == "__main__":
    unittest.main()
