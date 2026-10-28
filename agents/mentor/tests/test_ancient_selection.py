from pathlib import Path
import os
import sys
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from agents.mentor.noncombat import NoncombatPolicy, UnscoredSelection
from agents.mentor.runtime import MentorRuntime, default_config
from sts2.observation import Unsupported
from agents.mentor.tests.test_noncombat import observation


def card(name):
    return {'state': {'id': name, 'upgrade': 0, 'keywords': []}}


class AncientSelection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runtime = MentorRuntime(os.environ.get('MENTOR_CONFIG', default_config()))

    def policy(self, probs=None):
        policy = NoncombatPolicy(self.runtime)
        if probs is not None:
            policy.net = SimpleNamespace(distribution=lambda obs, actions, features: (probs, 0.0))
        return policy

    def selection(self, purpose, minimum, maximum, parent=None):
        obs = observation('grid_selection')
        cards = [card(name) for name in ('BASH', 'STRIKE_IRONCLAD', 'DEFEND_IRONCLAD')]
        obs['state']['status'].update(combat=None, deckCards=cards)
        obs['state']['selection'] = dict(purpose=purpose, min=minimum, max=maximum,
                                         cards=cards, parentRelic=parent)
        obs['actions'] = [{'id': 'choose_cards:', 'kind': 'select_grid', 'detail': {'metadata': {}}}]
        return obs

    def test_optional_grant_uses_skip_and_honors_maximum(self):
        obs = self.selection('grant', 0, 2)
        response, info = self.policy([.4, .3, .1, .2]).choose(obs)
        self.assertEqual(response['indices'], [0, 1])
        self.assertEqual(info['source'], 'ppo_optional_card_reward_proxy')
        obs['state']['selection']['max'] = 1
        self.assertEqual(self.policy([.4, .3, .1, .2]).choose(obs)[0]['indices'], [0])

    def test_optional_grant_can_skip_all_and_ties_prefer_skip(self):
        obs = self.selection('FromSimpleGridForRewards grant', 0, 3)
        self.assertEqual(self.policy([.2, .2, .2, .4]).choose(obs)[0]['indices'], [])
        self.assertEqual(self.policy([.25] * 4).choose(obs)[0]['indices'], [])

    def test_actual_model_scores_optional_grant_and_claws(self):
        for obs in (self.selection('grant', 0, 3), self.selection('transform', 0, 2, 'CLAWS')):
            response, info = self.policy().choose(obs)
            self.assertTrue(set(response['indices']) <= {0, 1, 2})
            self.assertLessEqual(len(response['indices']), obs['state']['selection']['max'])
        self.assertEqual(len(response['indices']), 2)
        self.assertEqual(info['count_rule'], 'fixed_maximum_for_claws')

    def test_unknown_optional_transform_and_invalid_probabilities_stop(self):
        with self.assertRaises(UnscoredSelection):
            self.policy().choose(self.selection('transform', 0, 2))
        with self.assertRaisesRegex(Unsupported, '確率'):
            self.policy([float('nan'), .2, .2, .6]).choose(self.selection('grant', 0, 2))

    def test_shop_copy_scores_grants_and_keeps_copy_intent(self):
        obs = self.selection('copy', 1, 1, 'DOLLYS_MIRROR')
        response, info = self.policy().choose(obs)
        self.assertEqual(len(response['indices']), 1)
        self.assertEqual(info['source'], 'ppo_copy_via_grant_proxy')
        self.assertEqual(info['purpose'], 'copy')

    def test_modifiers_reach_model_without_collapsing_same_name_cards(self):
        fields = {'remove': 'card_removal_option_enchantments',
                  'upgrade': 'smith_option_enchantments', 'copy': 'card_grant_option_enchantments',
                  'grant': 'card_grant_option_enchantments',
                  'transform': 'transform_select_deck_indices', 'enchant': 'enchant_select_deck_indices'}
        for purpose, field in fields.items():
            with self.subTest(purpose=purpose):
                plain, enchanted = card('BASH'), card('BASH')
                enchanted['state']['enchantment'] = {'id': 'ENCHANTMENT.SHARP', 'amount': 3}
                obs = self.selection(purpose, 1, 1)
                obs['state']['status']['deckCards'] = [plain, enchanted]
                obs['state']['selection'].update(cards=[enchanted, plain], enchantment='NIMBLE')
                seen = []
                def distribution(packet, actions, features):
                    seen.append(packet)
                    return self.runtime.net.distribution(packet, actions, features)
                policy = self.policy()
                policy.net = SimpleNamespace(distribution=distribution)
                response, _ = policy.choose(obs)
                self.assertEqual(len(response['indices']), 1)
                self.assertEqual(seen[0]['deck_enchantments'], [None, ['SHARP', 3]])
                expected = [1, 0] if purpose in {'transform', 'enchant'} else [['SHARP', 3], None]
                self.assertEqual(seen[0][field], expected)

    def test_optional_reward_preserves_upgrade_and_modifier_features(self):
        obs = self.selection('grant', 0, 1)
        obs['state']['selection']['cards'][0]['state']['enchantment'] = {'id': 'ENCHANTMENT.SHARP', 'amount': 3}
        obs['state']['selection']['cards'][1]['state']['upgrade'] = 1
        seen = []
        def distribution(packet, actions, features):
            seen.append(packet)
            return self.runtime.net.distribution(packet, actions, features)
        policy = self.policy()
        policy.net = SimpleNamespace(distribution=distribution)
        policy.choose(obs)
        self.assertEqual(seen[0]['card_reward_option_upgraded'], [False, True, False])
        self.assertEqual(seen[0]['card_reward_option_enchantments'], [['SHARP', 3], None, None])

    def test_bundle_preserves_modifier_order_for_every_card(self):
        plain, enchanted = card('BASH'), card('BASH')
        enchanted['state']['enchantment'] = {'id': 'ENCHANTMENT.SHARP', 'amount': 3}
        obs = observation('bundle_selection')
        obs['state']['bundles'] = [[enchanted, plain], [plain, enchanted]]
        obs['actions'] = [{'id': f'execute:{i}', 'kind': 'choose_bundle',
                           'detail': {'metadata': {'bundle_index': i}}} for i in range(2)]
        seen = []
        def distribution(packet, actions, features):
            seen.append(packet)
            return self.runtime.net.distribution(packet, actions, features)
        policy = self.policy()
        policy.net = SimpleNamespace(distribution=distribution)
        policy.choose(obs)
        self.assertEqual(seen[0]['card_grant_option_enchantments'], [['SHARP', 3], None, None, ['SHARP', 3]])

    def test_optional_shop_enchants_keep_name_and_choose_legal_maximum(self):
        runtime = self.runtime
        for parent, enchantment in [('GNARLED_HAMMER', 'SHARP'), ('KIFUDA', 'ADROIT')]:
            with self.subTest(parent=parent):
                obs = self.selection('enchant', 0, 2, parent)
                obs['state']['selection']['enchantment'] = enchantment
                policy = self.policy()
                class Net:
                    def distribution(self, packet, actions, features):
                        self.pending = packet['pending_enchantment']
                        return runtime.net.distribution(packet, actions, features)
                policy.net = Net()
                response, info = policy.choose(obs)
                self.assertEqual(len(response['indices']), 2)
                self.assertEqual(policy.net.pending, enchantment)
                self.assertEqual(info['count_rule'], 'fixed_maximum_for_' + parent.lower())

    def test_bundle_aggregates_all_cards_and_matches_explicit_index(self):
        obs = observation('bundle_selection')
        obs['state']['bundles'] = [[card('BASH'), card('STRIKE_IRONCLAD')],
                                   [card('DEFEND_IRONCLAD'), card('BASH')]]
        obs['actions'] = [{'id': f'execute:{i}', 'kind': 'choose_bundle',
                           'detail': {'metadata': {'bundle_index': i}}} for i in (1, 0)]
        response, info = self.policy([.1, .1, .4, .4]).choose(obs)
        self.assertEqual(response['action_id'], 'execute:1')
        self.assertEqual(info['chosen'], 1)
        self.assertEqual(info['source'], 'ppo_bundle_card_proxy')
        self.assertIn(self.policy().choose(obs)[0]['action_id'], ['execute:0', 'execute:1'])

    def test_bundle_rejects_missing_correspondence(self):
        obs = observation('bundle_selection')
        obs['state']['bundles'] = [[card('BASH')], [card('BASH')]]
        obs['actions'] = [{'id': 'execute', 'kind': 'choose_bundle',
                           'detail': {'metadata': {'bundle_index': 0}}}]
        with self.assertRaisesRegex(Unsupported, '対応'):
            self.policy().choose(obs)


if __name__ == '__main__':
    unittest.main()
