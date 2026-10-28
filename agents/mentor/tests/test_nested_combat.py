from copy import deepcopy
from pathlib import Path
import sys
import os
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from agents.mentor.combat import AFFLICTIONS, Unsupported, infer_enemy_moves
from agents.mentor.nested_combat import align_choice, public_projection, resume_choice, search_indices
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
        state, info = resume_choice(self.engine, before, {'action': 'play', 'card_index': 1}, current)
        self.assertEqual([c['id'] for c in state.pending_choice()['cards']], ['ANGER', 'STRIKE_IRONCLAD'])
        self.assertEqual(before, saved)

    def test_wish_waits_for_a_choice_and_preserves_card_disposal(self):
        source = wire()
        source['deck']['hand'] = [{'id': 'WISH', 'stable_idx': 0, 'kind': 'card', 'upgraded': False}]
        source['deck']['draw_pile'] = [
            {'id': name, 'stable_idx': i, 'kind': 'card', 'upgraded': False}
            for i, name in enumerate(['DEMON_FORM', 'STRIKE_IRONCLAD', 'ANGER'])]
        for index, expected in enumerate(['STRIKE_IRONCLAD', 'ANGER', 'DEMON_FORM_CARD']):
            with self.subTest(index=index):
                state = self.engine.state_from_dict(source)
                self.assertEqual(state.apply_step({'action': 'play', 'card_index': 0}), 'pending_choice')
                self.assertTrue(state.has_pending_play())
                self.assertEqual([c['id'] for c in state.pending_choice()['cards']],
                                 ['STRIKE_IRONCLAD', 'ANGER', 'DEMON_FORM_CARD'])
                state.apply({'action': 'choose', 'index': index, 'selection': [index]})
                result = self.engine.state_to_dict(state)['deck']
                self.assertEqual([c['id'] for c in result['hand']], [expected])
                self.assertEqual([c['id'] for c in result['exhaust_pile']], ['WISH'])
                self.assertFalse(state.has_pending_play())

    def test_wish_zero_or_one_candidate_does_not_open_a_choice(self):
        for count in (0, 1):
            with self.subTest(count=count):
                source = wire()
                source['deck']['hand'] = [{'id': 'WISH', 'stable_idx': 0, 'kind': 'card', 'upgraded': False}]
                source['deck']['draw_pile'] = [
                    {'id': 'BASH', 'stable_idx': 0, 'kind': 'card', 'upgraded': False}] if count else []
                state = self.engine.state_from_dict(source)
                state.apply({'action': 'play', 'card_index': 0})
                self.assertIsNone(state.pending_choice())
                result = self.engine.state_to_dict(state)['deck']
                self.assertEqual(sum(c['id'] == 'BASH' for c in result['hand']), count)

    def test_wish_override_survives_state_reconstruction_and_search(self):
        source = wire()
        source['deck']['hand'] = [{'id': 'WISH', 'stable_idx': 0, 'kind': 'card', 'upgraded': False}]
        state = self.engine.state_from_dict(source)
        self.engine.state_from_dict(wire())
        self.engine.mcts_recommend(state, sims=16, threads=1, hidden_info='beliefdraw', seed=0)
        state.apply({'action': 'play', 'card_index': 0})
        self.assertEqual(state.pending_choice()['kind'], 'add_from_draw_to_hand')

    def test_failed_state_reconstruction_does_not_reset_existing_state_rules(self):
        source = wire()
        source['deck']['hand'] = [{'id': 'WISH', 'stable_idx': 0, 'kind': 'card', 'upgraded': False}]
        state = self.engine.state_from_dict(source)
        invalid = wire()
        invalid['rng'].update(run_seed=0, counters={'not_a_stream': 0})
        with self.assertRaisesRegex(ValueError, 'not a stream'):
            self.engine.state_from_dict(invalid)
        state.apply({'action': 'play', 'card_index': 0})
        self.assertEqual(state.pending_choice()['kind'], 'add_from_draw_to_hand')

    def test_same_name_choices_keep_enchantment_and_world_order(self):
        source = wire()
        source['deck']['hand'] = [{'id': 'WISH', 'stable_idx': 0, 'kind': 'card', 'upgraded': False}]
        source['deck']['draw_pile'] = [
            {'id': 'DEFEND_IRONCLAD', 'stable_idx': 0, 'kind': 'card', 'upgraded': False,
             'enchantment': 'NIMBLE', 'enchantment_amount': 2},
            {'id': 'DEFEND_IRONCLAD', 'stable_idx': 1, 'kind': 'card', 'upgraded': False}]
        state = self.engine.state_from_dict(source)
        state.apply({'action': 'play', 'card_index': 0})
        current = self.engine.state_to_dict(state)
        offered = list(reversed(current['deck']['draw_pile']))
        align_choice(self.engine, state, current, offered)
        self.assertEqual([c['index'] for c in state.pending_choice()['cards']], [1, 0])
        state.apply({'action': 'choose', 'index': 0, 'selection': [0]})
        hand = self.engine.state_to_dict(state)['deck']['hand']
        self.assertEqual(len(hand), 1)
        self.assertIsNone(hand[0].get('enchantment'))

        state = self.engine.state_from_dict(source)
        state.apply({'action': 'play', 'card_index': 0})
        offered[1]['enchantment_amount'] = 99
        with self.assertRaisesRegex(Unsupported, '属性が再生中'):
            align_choice(self.engine, state, current, offered)

    def test_catastrophe_reconstructs_only_an_already_visible_random_outcome(self):
        source = wire()
        source['deck']['hand'] = [{'id': 'CATASTROPHE', 'stable_idx': 0, 'kind': 'card', 'upgraded': False}]
        source['deck']['draw_pile'] = [
            {'id': name, 'stable_idx': i, 'kind': 'card', 'upgraded': False}
            for i, name in enumerate(['WISH', 'STRIKE_IRONCLAD', 'ANGER', 'BASH', 'DEFEND_IRONCLAD'])]
        action = {'action': 'play', 'card_index': 0}
        original = deepcopy(source)
        default = self.engine.state_from_dict(source)
        default.apply(action)
        default_result = public_projection(self.engine.state_to_dict(default))
        for seed in range(100):
            actual = deepcopy(source)
            actual['rng']['run_seed'] = seed
            state = self.engine.state_from_dict(actual)
            state.apply(action)
            choice = state.pending_choice()
            if (choice and self.engine.state_to_dict(state)['deck']['play_pile'][-1]['id'] == 'WISH'
                    and public_projection(self.engine.state_to_dict(state)) != default_result):
                current = self.engine.state_to_dict(state)
                offered = [(c['id'], c['upgraded']) for c in choice['cards']]
                replay, info = resume_choice(self.engine, source, action, current, offered)
                self.assertEqual(public_projection(self.engine.state_to_dict(replay)), public_projection(current))
                self.assertEqual(info['method'], 'observed_random_outcome')
                self.assertEqual(source, original)
                replay.apply({'action': 'choose', 'index': 0, 'selection': [0]})
                self.assertFalse(replay.has_pending_play())
                self.assertFalse(replay.has_suspended_walk())
                self.assertIsNone(replay.pending_choice())
                current['player']['hp'] -= 1
                with self.assertRaisesRegex(Unsupported, '4096試行'):
                    resume_choice(self.engine, source, action, current, offered)
                return
        self.fail('Wish自動使用の試験局面を構成できない')

    def test_catastrophe_surfaces_and_replays_the_second_wish_choice(self):
        source = wire()
        source['deck']['hand'] = [{'id': 'CATASTROPHE', 'stable_idx': 0, 'kind': 'card', 'upgraded': False}]
        source['deck']['draw_pile'] = [
            {'id': name, 'stable_idx': i, 'kind': 'card', 'upgraded': False}
            for i, name in enumerate(['WISH', 'WISH', 'STRIKE_IRONCLAD', 'ANGER', 'BASH', 'DEFEND_IRONCLAD'])]
        action = {'action': 'play', 'card_index': 0}
        for seed in range(100):
            actual = deepcopy(source)
            actual['rng']['run_seed'] = seed
            state = self.engine.state_from_dict(actual)
            state.apply(action)
            first = state.pending_choice()
            if first is None:
                continue
            current = self.engine.state_to_dict(state)
            pick = next((i for i, c in enumerate(first['cards']) if c['id'] == 'STRIKE_IRONCLAD'), None)
            if pick is None:
                continue
            cards = [current['deck']['draw_pile'][c['index']] for c in first['cards']]
            state.apply({'action': 'choose', 'selection': [pick]})
            second = state.pending_choice()
            if second is None:
                continue
            next_current = self.engine.state_to_dict(state)
            offered = [(c['id'], c['upgraded']) for c in second['cards']]
            history = [{'current': current, 'cards': cards, 'indices': [pick]}]
            replay, info = resume_choice(self.engine, source, action, next_current, offered, history)
            self.assertEqual(info['earlier_choices'], 1)
            self.assertEqual(public_projection(self.engine.state_to_dict(replay)), public_projection(next_current))
            self.assertTrue(replay.has_pending_play())
            replay.apply({'action': 'choose', 'selection': [0]})
            self.assertIsNone(replay.pending_choice())
            self.assertFalse(replay.has_pending_play())
            return
        self.fail('2回目のWish選択が公開されない')

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
        self.assertIsNotNone(resume_choice(self.engine, before, action, current)[0].pending_choice())
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

    def test_public_comparison_checks_history_without_comparing_unobservable_storage(self):
        before, current = self.prepared_outcome()
        expected = public_projection(current)
        current['deck']['hand'][0]['combat_vars'] = {'free_until_played': 0}
        self.assertEqual(public_projection(current), expected)
        current['player']['cards_played_this_turn'] = [1, 0, 0, 0, 0]
        self.assertNotEqual(public_projection(current), expected)
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
