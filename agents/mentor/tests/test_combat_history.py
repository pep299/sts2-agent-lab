from copy import deepcopy
import unittest

from agents.mentor.combat import make_wire
from agents.mentor.tests.test_combat import observation
from sts2.observation import Unsupported


class PublicHistoryContract(unittest.TestCase):
    registries = {'card': {'A', 'B'}, 'power': {'JUGGLING'},
                  'relic': {'PEN_NIB', 'VAMBRACE', 'CENTENNIAL_PUZZLE'}, 'potion': set()}

    def test_started_finished_and_block_entries_are_distinct(self):
        obs = observation()
        combat = obs['state']['status']['combat']
        plays = [{'playId': i, 'ownerId': 1, 'card': {'type': kind}}
                 for i, kind in [(1, 'Attack'), (2, 'Attack'), (3, 'Skill')]]
        combat['history'].update(playsStarted=plays, playsFinished=[plays[0], plays[2]],
            blockGained=[{'receiverId': 1, 'cardPlay': plays[1]},
                         {'receiverId': 1, 'cardPlay': plays[1]},
                         {'receiverId': 1, 'cardPlay': {'playId': 50, 'ownerId': 1}},
                         {'receiverId': 99, 'cardPlay': plays[0]},
                         {'receiverId': 1, 'cardPlay': None}])
        combat['boundCardPlayedThisTurn'] = True
        obs['state']['status']['powers'] = [{'id': 'POWER.JUGGLING', 'amount': 1, 'displayAmount': 1}]
        player = make_wire(obs, self.registries)['player']
        self.assertEqual(player['cards_started_this_turn'], [2, 1, 0, 0, 0])
        self.assertEqual(player['cards_played_this_turn'], [1, 1, 0, 0, 0])
        self.assertEqual(player['current_card_play'], 2)
        self.assertEqual(player['next_card_play'], 51)
        self.assertEqual(player['block_gained_card_plays_this_turn'], [2, 2, 50])
        self.assertEqual(player['powers'][0]['counter'], 2)
        self.assertTrue(player['bound_card_played_this_turn'])

    def test_relic_consumption_and_live_card_reference_are_preserved(self):
        obs = observation()
        obs['state']['status']['relicDetails'] = [
            {'id': 'RELIC.PEN_NIB', 'counter': 10, 'effectState': {
                'attacksPlayed': 10, 'attackToDouble': {'id': 'CARD.A', 'instance': 30}}},
            {'id': 'RELIC.CENTENNIAL_PUZZLE', 'counter': None, 'effectState': {'usedThisCombat': True}},
            {'id': 'RELIC.VAMBRACE', 'counter': None, 'effectState': {
                'blockGainedThisCombat': True, 'triggeringCard': {'id': 'CARD.B', 'instance': 999}}}]
        player = make_wire(obs, self.registries)['player']
        self.assertEqual([r['counter'] for r in player['relics']], [0, 1, 1])
        self.assertEqual(player['pen_nib_attack_to_double'], {'pile': 'hand', 'index': 0})
        self.assertIsNone(player['vambrace_triggering_card'])
        obs['state']['status']['relicDetails'][2]['effectState']['blockGainedThisCombat'] = False
        with self.assertRaisesRegex(Unsupported, 'カード個体'):
            make_wire(obs, self.registries)

    def test_status_and_curse_history_use_the_engine_type_buckets(self):
        for kind, expected in [('Curse', [0, 0, 0, 1, 0]), ('Status', [0, 0, 0, 0, 1])]:
            obs = observation()
            play = {'playId': 1, 'ownerId': 1, 'card': {'type': kind}}
            obs['state']['status']['combat']['history'].update(playsStarted=[play], playsFinished=[play])
            player = make_wire(obs, self.registries)['player']
            self.assertEqual(player['cards_started_this_turn'], expected)
            self.assertEqual(player['cards_played_this_turn'], expected)

    def test_public_top_has_order_and_identity_but_other_draw_cards_do_not(self):
        obs = observation()
        combat = obs['state']['status']['combat']
        combat['drawKnownTop'] = [deepcopy(combat['draw']['cards'][0]['state'])]
        original = deepcopy(obs)
        wire = make_wire(obs, self.registries)
        self.assertEqual(obs, original)
        self.assertEqual([c['id'] for c in wire['deck']['draw_pile']], ['B', 'A'])
        self.assertEqual(wire['deck']['pinned_top'], [0])
        self.assertEqual(wire['public_instances']['31'], {'pile': 'draw', 'index': 0})
        self.assertNotIn('32', wire['public_instances'])
        combat['draw']['cards'].reverse()
        for card in combat['draw']['cards']:
            card['state']['instance'] = None
        self.assertEqual(make_wire(obs, self.registries), wire)
        self.assertEqual(original['state']['status']['combat']['drawKnownTop'][0]['instance'], 31)
        combat['drawKnownTop'] = []
        shuffled = make_wire(obs, self.registries)
        self.assertEqual(shuffled['deck']['pinned_top'], [])
        self.assertNotIn('31', shuffled['public_instances'])

    def test_same_name_top_is_matched_by_all_public_attributes(self):
        obs = observation()
        combat = obs['state']['status']['combat']
        special = deepcopy(combat['draw']['cards'][1])
        special['state'].update(instance=90, enchantment={'id': 'ENCHANTMENT.NIMBLE', 'amount': 2})
        combat['draw']['cards'].append(special)
        combat['drawKnownTop'] = [deepcopy(special['state'])]
        wire = make_wire(obs, self.registries | {'enchantment': {'NIMBLE'}})
        self.assertEqual(wire['deck']['draw_pile'][0]['enchantment_amount'], 2)
        self.assertEqual(wire['public_instances']['90'], {'pile': 'draw', 'index': 0})
        combat['draw']['cards'].pop()
        with self.assertRaisesRegex(Unsupported, '山札集合'):
            make_wire(obs, self.registries | {'enchantment': {'NIMBLE'}})

    def test_completed_play_requires_a_start_and_duplicate_ids_are_rejected(self):
        for started, finished in [([], [{'playId': 1, 'ownerId': 1, 'card': {'type': 'Attack'}}]),
                                  ([{'playId': 1, 'ownerId': 1, 'card': {'type': 'Attack'}}] * 2, [])]:
            obs = observation()
            obs['state']['status']['combat']['history'].update(playsStarted=started, playsFinished=finished)
            with self.assertRaises(Unsupported):
                make_wire(obs, self.registries)


if __name__ == '__main__':
    unittest.main()
