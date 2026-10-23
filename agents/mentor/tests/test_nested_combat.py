from copy import deepcopy
from pathlib import Path
import sys
import os
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from agents.mentor.combat import AFFLICTIONS, Unsupported, infer_enemy_moves
from agents.mentor.nested_combat import public_projection, resume_choice, search_indices
from agents.mentor.policy import Mentor
from agents.mentor.runtime import default_config


def wire():
    def card(name):
        return {'id': name, 'stable_idx': 0, 'kind': 'card', 'upgraded': False}
    return {'wire_version': 1, 'game_version': 'v0.111.0', 'phase': 'PlayerPlayPhase',
        'round': 1, 'turn': 1, 'side': 'Player', 'combat_id': 0, 'intent_amounts': 'effective', 'is_elite': False,
        'deck': {'hand': [card('ANGER'), card('PREPARED')],
                 'draw_pile': [card('DEFEND_IRONCLAD'), card('STRIKE_IRONCLAD')],
                 'discard_pile': [], 'exhaust_pile': [], 'master_deck': []},
        'encounter': [{'kind': 'KNOWLEDGE_DEMON', 'uid': 9, 'hp': 40, 'max_hp': 40, 'block': 0,
                       'powers': [], 'intents': [{'kind': 'Attack', 'amount': 11}], 'intent_history': [],
                       'is_dead': False, 'is_escaped': False}],
        'player': {'class': 'ironclad', 'hp': 70, 'max_hp': 80, 'energy': 3, 'max_energy': 3,
                   'energy_regen_per_turn': 3, 'block': 0, 'gold': 0, 'powers': [], 'relics': [], 'potions': []},
        'rng': {'seed': 0, 'ascension': 0}}


class ReplayContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = Mentor(os.environ.get('MENTOR_CONFIG', default_config())).engine

    def prepared_outcome(self):
        before = self.engine.state_to_dict(self.engine.state_from_dict(wire()))
        actual = deepcopy(before)
        actual['deck']['draw_pile'].reverse()
        state = self.engine.state_from_dict(actual)
        state.apply({'action': 'play', 'card_index': 1})
        return before, self.engine.state_to_dict(state)

    def test_already_visible_draw_is_replayed_without_next_draw_knowledge(self):
        before, current = self.prepared_outcome()
        saved = deepcopy(before)
        state = resume_choice(self.engine, before, {'action': 'play', 'card_index': 1}, current)
        self.assertEqual([c['id'] for c in state.pending_choice()['cards']], ['ANGER', 'STRIKE_IRONCLAD'])
        self.assertEqual(before, saved)

    def test_board_disagreement_rejects_child_search(self):
        before, current = self.prepared_outcome()
        current['player']['hp'] -= 1
        with self.assertRaisesRegex(Unsupported, 'player'):
            resume_choice(self.engine, before, {'action': 'play', 'card_index': 1}, current)

    def test_reaped_enemy_does_not_hide_survivor_disagreement(self):
        before = wire()
        before['deck']['hand'] = [{'id': 'HEADBUTT', 'stable_idx': 0, 'kind': 'card', 'upgraded': False}]
        before['deck']['discard_pile'] = [
            {'id': 'ANGER', 'stable_idx': 0, 'kind': 'card', 'upgraded': False},
            {'id': 'BASH', 'stable_idx': 1, 'kind': 'card', 'upgraded': False}]
        enemy = before['encounter'][0]
        before['encounter'] = [dict(enemy, kind='TOADPOLE', uid=1, hp=40),
                               dict(enemy, kind='TOADPOLE', uid=2, hp=1)]
        action = {'action': 'play', 'card_index': 0, 'target_index': 1}
        state = self.engine.state_from_dict(before)
        state.apply(action)
        current = self.engine.state_to_dict(state)
        current['encounter'] = [e for e in current['encounter'] if e['hp'] > 0]
        self.assertIsNotNone(resume_choice(self.engine, before, action, current).pending_choice())
        current['encounter'][0]['hp'] -= 1
        with self.assertRaisesRegex(Unsupported, 'encounter'):
            resume_choice(self.engine, before, action, current)

    def test_unexplainable_draw_is_rejected(self):
        before, current = self.prepared_outcome()
        current['deck']['hand'][-1]['id'] = 'BASH'
        with self.assertRaisesRegex(Unsupported, '公開済みドロー'):
            resume_choice(self.engine, before, {'action': 'play', 'card_index': 1}, current)

    def test_public_projection_ignores_draw_order_but_not_card_state(self):
        before, current = self.prepared_outcome()
        original = public_projection(current)
        current['deck']['draw_pile'].reverse()
        self.assertEqual(public_projection(current), original)
        current['deck']['hand'][0]['upgraded'] = True
        self.assertNotEqual(public_projection(current), original)

    def test_supported_afflictions_reach_the_fixed_engine(self):
        for name in AFFLICTIONS.values():
            with self.subTest(affliction=name):
                source = wire()
                if name == 'Tainted':
                    source['deck']['hand'][0]['id'] = 'DEFEND_IRONCLAD'
                source['deck']['hand'][0].update(affliction=name, affliction_stacks=2)
                exported = self.engine.state_to_dict(self.engine.state_from_dict(source))['deck']['hand'][0]
                self.assertEqual((exported['affliction'], exported['affliction_stacks']), (name, 2))

    def test_public_debuff_intent_keeps_future_enemy_attacks(self):
        source = wire()
        source['encounter'][0]['intents'] = [{'kind': 'Debuff', 'amount': 0, 'times': 1}]
        infer_enemy_moves(source, self.engine)
        state = self.engine.state_from_dict(source)
        self.assertEqual(self.engine.state_to_dict(state)['encounter'][0]['move_state'], 'CURSE_OF_KNOWLEDGE')
        starting_hp = self.engine.state_to_dict(state)['player']['hp']
        for _ in range(3):
            state.apply({'action': 'end_turn'})
            for _ in range(3):
                if state.pending_choice() is None:
                    break
                state.apply({'action': 'choose', 'index': 0, 'selection': [0]})
        self.assertLess(self.engine.state_to_dict(state)['player']['hp'], starting_hp)

    def test_indistinguishable_enemy_moves_remain_explicit_assumptions(self):
        source = wire()
        source['turn'] = 2
        source['encounter'][0].update(kind='SKULKING_COLONY', powers=[], intents=[
            {'kind': 'Attack', 'amount': 14, 'times': 1}])
        infer_enemy_moves(source, self.engine)
        self.assertEqual(source['public_ai_assumptions'][0]['alternatives'], ['ZOOM_MOVE', 'ZOOM_MOVE_2'])

    def test_enchantment_stack_reaches_the_fixed_engine(self):
        source = wire()
        source['deck']['hand'][0].update(enchantment='INSTINCT', enchantment_amount=1,
                                       base_cost=0, cost_override=0)
        exported = self.engine.state_to_dict(self.engine.state_from_dict(source))['deck']['hand'][0]
        self.assertEqual((exported['enchantment'], exported['enchantment_amount'], exported['cost_override']),
                         ('Instinct', 1, 0))

    def test_public_comparison_does_not_claim_unobserved_internal_counters(self):
        before, current = self.prepared_outcome()
        expected = public_projection(current)
        current['player']['cards_played_this_turn'] = [1, 0, 0, 0, 0]
        current['deck']['hand'][0]['combat_vars'] = {'free_until_played': 0}
        self.assertEqual(public_projection(current), expected)
        current['player']['hp'] -= 1
        self.assertNotEqual(public_projection(current), expected)

    def test_multi_pick_search_returns_the_complete_distinct_set(self):
        source = wire()
        source['deck']['hand'][1]['upgraded'] = True
        state = self.engine.state_from_dict(source)
        state.apply({'action': 'play', 'card_index': 1})
        pending = state.pending_choice()
        self.assertEqual((pending['min_select'], pending['max_select']), (2, 2))
        indices, searches = search_indices(self.engine, state, 2, 2, len(pending['cards']), sims=100, threads=1)
        self.assertEqual(len(indices), 2)
        self.assertEqual(len(set(indices)), 2)
        self.assertEqual(len(searches), 2)

    def test_world_generated_options_keep_the_potion_effect(self):
        state = self.engine.state_from_dict(wire())
        state.open_injected_choice('add_generated_free_to_hand', [{'id': 'BASH', 'upgraded': False}],
                                   1, 1, False, False)
        indices, searches = search_indices(self.engine, state, 1, 1, 1, sims=100, threads=1)
        self.assertEqual(indices, [0])
        state.apply(searches[0])
        added = [c for c in self.engine.state_to_dict(state)['deck']['hand'] if c['id'] == 'BASH']
        self.assertEqual(len(added), 1)
        self.assertEqual(added[0]['cost_override'], 0)


if __name__ == '__main__':
    unittest.main()
