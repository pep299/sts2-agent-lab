import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from agents.mentor.combat import Unsupported, is_boss, make_wire, match_action, wire_cards


def observation():
    def card(name, instance):
        return {'state': {'id': 'CARD.' + name, 'instance': instance, 'upgrade': 0,
                         'keywords': [], 'facts': {'type': 'Skill', 'energyCost': {
                             'canonical': 1, 'current': 1, 'costsX': False,
                             'local': 1, 'afterTurn': 1, 'afterPlay': 1, 'afterTurnAndPlay': 1,
                             'unmodified': 1, 'modifiers': []},
                         'dynamicVars': []}}}
    return {'state': {'status': {
        'hp': 70, 'maxHp': 80, 'block': 0, 'energy': 3, 'maxEnergy': 3, 'gold': 99,
        'powers': [], 'relicDetails': [], 'potionBelt': {'slots': []}, 'deckCards': [],
        'map': None, 'ascension': 0,
        'combat': {'turn': 1, 'round': 1, 'side': 'Player', 'ownerId': 1,
                   'history': {'coverage': 'current_turn', 'playsStarted': [], 'playsFinished': [],
                               'blockGained': [], 'draws': []}, 'boundCardPlayedThisTurn': False,
                   'maxEnergy': 3, 'stars': 0, 'pets': [], 'orbs': [],
                   'hand': {'cards': [card('A', 30)]},
                   'draw': {'cards': [card('B', 31), card('A', 32)]},
                   'discard': {'cards': []}, 'exhaust': {'cards': []},
                   'enemies': [{'id': 17, 'modelId': 'MONSTER.X', 'hp': 10, 'maxHp': 10,
                                'block': 0, 'powers': [], 'intents': []},
                               {'id': 42, 'modelId': 'MONSTER.X', 'hp': 20, 'maxHp': 20,
                                'block': 0, 'powers': [], 'intents': []}]}}},
        'capabilities': {'gameVersion': 'v0.111.0', 'observationRevision': 'public-state-v4'},
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
        state['facts']['energyCost'].update(local=1, afterTurn=1, afterPlay=1, afterTurnAndPlay=1)
        card = make_wire(obs, self.registries | {'enchantment': {'INSTINCT'}})['deck']['hand'][0]
        self.assertEqual((card['enchantment'], card['enchantment_amount'], card['cost_override']), ('INSTINCT', 1, 0))

    def test_cost_lifetimes_are_local_and_do_not_bake_in_global_discount(self):
        obs = observation()
        cost = obs['state']['status']['combat']['hand']['cards'][0]['state']['facts']['energyCost']
        cost.update(canonical=4, unmodified=4, current=0, local=2, afterTurn=4, afterPlay=1, afterTurnAndPlay=3,
                    modifiers=[{'type': 'Relative', 'amount': -1, 'isReduceOnly': False, 'expiration': 0},
                               {'type': 'Relative', 'amount': -2, 'isReduceOnly': False, 'expiration': 2},
                               {'type': 'Relative', 'amount': 1, 'isReduceOnly': False, 'expiration': 4}])
        card = make_wire(obs, self.registries)['deck']['hand'][0]
        self.assertEqual([*card['public_costs'].values(), card['cost_override']],
                         [2, 4, 1, 3, 0])
        self.assertTrue({'base_cost', 'persistent_cost', 'played_cost', 'stable_cost'}.isdisjoint(card))
        del cost['afterPlay']
        with self.assertRaisesRegex(Unsupported, '揃っていない'):
            make_wire(obs, self.registries)

    def test_legacy_discount_without_lifetime_is_rejected(self):
        obs = observation()
        obs['state']['status']['combat']['hand']['cards'][0]['state']['facts']['energyCost'] = {
            'canonical': 1, 'current': 0, 'costsX': False}
        with self.assertRaisesRegex(Unsupported, '失効後費用'):
            make_wire(obs, self.registries)

    def test_wither_validation_is_shared_by_snapshot_and_selection_candidates(self):
        obs = observation()
        c = obs['state']['status']['combat']['hand']['cards'][0]['state']
        c.update(id='CARD.WITHER', special={'fakeUpgradeLevel': 2, 'baseDamage': 9})
        c['facts']['dynamicVars'] = [{'name': 'Damage', 'baseValue': 9}]
        regs = self.registries | {'card': {'A', 'B', 'WITHER'}}
        before = copy.deepcopy(obs)
        normal = make_wire(obs, regs)['deck']['hand']
        candidates = wire_cards([{'cardDetails': {'state': c}}], regs)
        self.assertEqual(normal, candidates)
        self.assertEqual(normal[0]['base_damage'], 9)
        self.assertEqual(obs, before)
        for level in (-1, True, 1.5):
            c['special']['fakeUpgradeLevel'] = level
            with self.assertRaisesRegex(Unsupported, '特殊値'):
                wire_cards([{'state': c}], regs)
        c['special']['fakeUpgradeLevel'] = 2
        c['facts']['dynamicVars'][0]['baseValue'] = 6
        with self.assertRaisesRegex(Unsupported, '特殊値'):
            wire_cards([{'state': c}], regs)

    def test_temporary_retain_and_sly_are_not_permanent_keywords(self):
        obs = observation()
        c = obs['state']['status']['combat']['hand']['cards'][0]['state']
        c['facts'].update(retain=True, sly=True)
        self.assertEqual(make_wire(obs, self.registries)['deck']['hand'][0]['flags'], ['retain_turn', 'sly_turn'])
        c['keywords'] = ['Retain', 'Sly']
        self.assertEqual(make_wire(obs, self.registries)['deck']['hand'][0]['flags'], ['retain', 'sly'])

    def test_pickup_relics_are_omitted_only_from_combat_and_melting_is_preserved(self):
        obs = observation()
        obs['state']['status']['relicDetails'] = [
            {'id': 'RELIC.DOWSING_ROD', 'counter': None},
            {'id': 'RELIC.NEOWS_SACRIFICE', 'counter': None},
            {'id': 'RELIC.VAJRA', 'counter': 0, 'isMelted': True}]
        before = copy.deepcopy(obs)
        relics = make_wire(obs, self.registries | {'relic': {'VAJRA'}})['player']['relics']
        self.assertEqual(relics, [{'id': 'VAJRA', 'counter': 0, 'is_melted': True}])
        self.assertEqual(obs, before)
        obs['state']['status']['relicDetails'].append({'id': 'RELIC.UNKNOWN', 'counter': None})
        with self.assertRaises(Unsupported):
            make_wire(obs, self.registries | {'relic': {'VAJRA'}})

    def test_power_amount_display_and_public_effect_state_are_distinct(self):
        obs = observation()
        obs['state']['status']['powers'] = [
            {'id': 'POWER.PANACHE', 'amount': 10, 'displayAmount': 2},
            {'id': 'POWER.SURROUNDED', 'amount': 1, 'displayAmount': 1, 'facing': 'Left'},
            {'id': 'POWER.CRIMSON_MANTLE', 'amount': 8, 'displayAmount': 8,
             'dynamicVars': [{'name': 'SelfDamage', 'baseValue': 3}]}]
        powers = make_wire(obs, self.registries | {'power': {'PANACHE', 'SURROUNDED', 'CRIMSON_MANTLE'}})['player']['powers']
        self.assertEqual(powers, [{'name': 'PANACHE', 'amount': 10, 'display': 2},
                                 {'name': 'SURROUNDED', 'amount': 1, 'display': 1, 'counter': 1},
                                 {'name': 'CRIMSON_MANTLE', 'amount': 8, 'display': 8, 'counter': 3}])

    def test_legacy_progress_amount_is_not_reinterpreted_as_stack(self):
        obs = observation()
        obs['state']['status']['powers'] = [{'id': 'POWER.PANACHE', 'amount': 2}]
        obs['capabilities']['observationRevision'] = 'public-state-v3'
        with self.assertRaisesRegex(Unsupported, 'public-state-v4'):
            make_wire(obs, self.registries | {'power': {'PANACHE'}})

    def test_parent_card_in_play_is_preserved(self):
        obs = observation()
        combat = obs['state']['status']['combat']
        combat['play'] = {'cards': combat['hand']['cards']}
        combat['hand'] = {'cards': []}
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
