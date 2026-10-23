import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from combat import Unsupported, is_boss, make_wire, match_action


def observation():
    def card(name, instance):
        return {'state': {'id': 'CARD.' + name, 'instance': instance, 'upgrade': 0,
                         'keywords': [], 'facts': {'type': 'Skill', 'energyCost': {
                             'canonical': 1, 'current': 1, 'costsX': False}, 'dynamicVars': []}}}
    return {'state': {'status': {
        'hp': 70, 'maxHp': 80, 'block': 0, 'energy': 3, 'maxEnergy': 3, 'gold': 99,
        'powers': [], 'relicDetails': [], 'potionBelt': {'slots': []}, 'deckCards': [],
        'map': None, 'ascension': 0,
        'combat': {'turn': 1, 'maxEnergy': 3, 'stars': 0, 'pets': [], 'orbs': [],
                   'hand': {'cards': [card('A', 30)]},
                   'draw': {'cards': [card('B', 31), card('A', 32)]},
                   'discard': {'cards': []}, 'exhaust': {'cards': []},
                   'enemies': [{'id': 17, 'modelId': 'MONSTER.X', 'hp': 10, 'maxHp': 10,
                                'block': 0, 'powers': [], 'intents': []},
                               {'id': 42, 'modelId': 'MONSTER.X', 'hp': 20, 'maxHp': 20,
                                'block': 0, 'powers': [], 'intents': []}]}}},
        'actions': [{'id': 'play-other-enemy', 'kind': 'play', 'detail': {
            'metadata': {'card_index': 0, 'target_id': 42}}}]}


class CombatContract(unittest.TestCase):
    registries = {'card': {'A', 'B'}, 'power': set(), 'relic': set(), 'potion': set()}

    def test_enemy_slot_maps_to_public_id(self):
        result = match_action({'action': 'play', 'card_index': 0, 'target_index': 1}, observation())
        self.assertEqual(result['id'], 'play-other-enemy')

    def test_unavailable_target_does_not_change_to_first_enemy(self):
        self.assertIsNone(match_action({'action': 'play', 'card_index': 0, 'target_index': 0}, observation()))

    def test_dense_potion_index_maps_to_occupied_belt_slot_and_engine_default_target(self):
        obs = observation()
        obs['state']['status']['potionBelt']['slots'] = [{'index': 0, 'potion': None},
            {'index': 1, 'potion': None}, {'index': 2, 'potion': {'id': 'POTION.WEAK_POTION', 'targetType': 'AnyEnemy'}}]
        obs['actions'] = [{'id': 'use-slot-2-enemy-17', 'kind': 'potion', 'detail': {
            'metadata': {'potion_index': 2, 'target_id': 17}}}]
        self.assertEqual(match_action({'action': 'drink_potion', 'slot': 0, 'target_index': None}, obs)['id'],
                         'use-slot-2-enemy-17')

    def test_self_potion_uses_the_single_public_recipient(self):
        obs = observation()
        obs['state']['status']['potionBelt']['slots'] = [{'index': 0, 'potion': {
            'id': 'POTION.STRENGTH_POTION', 'targetType': 'AnyPlayer'}}]
        obs['actions'] = [{'id': 'use-player-99', 'kind': 'potion', 'detail': {
            'metadata': {'potion_index': 0, 'target_id': 99}}}]
        self.assertEqual(match_action({'action': 'drink_potion', 'slot': 0}, obs)['id'], 'use-player-99')

    def test_ambiguous_target_is_rejected(self):
        obs = observation()
        obs['actions'].append(copy.deepcopy(obs['actions'][0]))
        with self.assertRaises(Unsupported):
            match_action({'action': 'play', 'card_index': 0, 'target_index': 1}, obs)

    def test_hidden_draw_order_and_instances_do_not_change_input(self):
        original = observation()
        changed = copy.deepcopy(original)
        pile = changed['state']['status']['combat']['draw']['cards']
        pile.reverse()
        for c in pile:
            c['state']['instance'] += 1000
        self.assertEqual(make_wire(original, self.registries), make_wire(changed, self.registries))

    def test_input_is_unchanged(self):
        obs = observation()
        original = copy.deepcopy(obs)
        make_wire(obs, self.registries)
        self.assertEqual(obs, original)

    def test_unknown_power_is_not_dropped(self):
        obs = observation()
        obs['state']['status']['powers'] = [{'id': 'POWER.UNKNOWN', 'amount': 1}]
        with self.assertRaises(Unsupported):
            make_wire(obs, self.registries)

    def test_enchantment_is_not_dropped(self):
        obs = observation()
        obs['state']['status']['combat']['hand']['cards'][0]['state']['enchantment'] = {'id': 'UNKNOWN'}
        with self.assertRaises(Unsupported):
            make_wire(obs, self.registries)

    def test_tainted_affliction_preserves_amount(self):
        obs = observation()
        obs['state']['status']['combat']['hand']['cards'][0]['state']['affliction'] = {
            'id': 'AFFLICTION.TAINTED', 'amount': 2, 'displayAmount': 2}
        card = make_wire(obs, self.registries)['deck']['hand'][0]
        self.assertEqual((card['affliction'], card['affliction_stacks']), ('Tainted', 2))

    def test_unknown_affliction_is_rejected(self):
        obs = observation()
        obs['state']['status']['combat']['hand']['cards'][0]['state']['affliction'] = {
            'id': 'AFFLICTION.UNKNOWN', 'amount': 2}
        with self.assertRaises(Unsupported):
            make_wire(obs, self.registries)

    def test_enchantment_preserves_stack_and_resolved_cost(self):
        obs = observation()
        state = obs['state']['status']['combat']['hand']['cards'][0]['state']
        state['enchantment'] = {'id': 'ENCHANTMENT.INSTINCT', 'amount': 1}
        state['facts']['energyCost']['current'] = 0
        card = make_wire(obs, self.registries | {'enchantment': {'INSTINCT'}})['deck']['hand'][0]
        self.assertEqual((card['enchantment'], card['enchantment_amount'], card['cost_override']), ('INSTINCT', 1, 0))

    def test_parent_card_in_play_is_preserved(self):
        obs = observation()
        combat = obs['state']['status']['combat']
        combat['play'] = {'cards': combat['hand']['cards']}
        self.assertEqual(make_wire(obs, self.registries)['deck']['play_pile'][0]['id'], 'A')

    def test_orb_order_values_and_capacity_are_preserved(self):
        obs = observation()
        obs['state']['status']['combat'].update(orbCapacity=2, orbs=[
            {'id': 'ORB.DARK_ORB', 'passive': 6, 'evoke': 17},
            {'id': 'ORB.LIGHTNING_ORB', 'passive': 3, 'evoke': 8}])
        player = make_wire(obs, self.registries | {'orb': {'DARK', 'LIGHTNING'}})['player']
        self.assertEqual(player['orb_slots'], 2)
        self.assertEqual(player['orbs'], [{'type': 'DARK', 'passive': 6, 'evoke': 17},
                                          {'type': 'LIGHTNING', 'passive': 3, 'evoke': 8}])

    def test_boss_uses_public_map_instead_of_shared_room_class(self):
        obs = observation()
        obs['state']['status']['room'] = {'type': 'CombatRoom'}
        obs['state']['status']['map'] = {'current': {'col': 3, 'row': 16},
                                       'boss': {'col': 3, 'row': 16}}
        self.assertTrue(is_boss(obs))

    def test_missing_map_is_not_a_boss(self):
        self.assertFalse(is_boss(observation()))


if __name__ == '__main__':
    unittest.main()
