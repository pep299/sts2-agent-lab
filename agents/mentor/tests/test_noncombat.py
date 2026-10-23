from pathlib import Path
import os
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from agents.mentor.noncombat import NoncombatPolicy
from agents.mentor.runtime import MentorRuntime, default_config
from sts2.observation import Unsupported


def observation(phase):
    return {'state': {'phase': phase, 'status': {'act': 1, 'floor': 0, 'hp': 80, 'maxHp': 80,
        'gold': 99, 'ascension': 0, 'deckCards': [], 'relics': [],
        'potionBelt': {'slots': [{'potion': None}]},
        'map': {'nodes': [{'coord': {'row': 1, 'col': i}, 'roomType': 'Monster', 'children': []}
                          for i in range(2)], 'current': None, 'boss': None, 'bossId': None}}},
        'actions': []}


class NoncombatInterface(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runtime = MentorRuntime(os.environ.get('MENTOR_CONFIG', default_config()))

    def test_map_uses_public_semantics_without_native_host_fields(self):
        obs = observation('map')
        obs['actions'] = [{'id': f'move:{i}', 'kind': 'map', 'detail': {
            'metadata': {'row': 1, 'col': i, 'room_type': 'Monster'}}} for i in range(2)]
        response, info = NoncombatPolicy(self.runtime).choose(obs)
        self.assertIn(response['action_id'], ['move:0', 'move:1'])
        self.assertEqual(info['source'], 'ppo')

    def test_card_offer_uses_public_card_ids_without_native_kind(self):
        obs = observation('rewards')
        obs['actions'] = [
            {'id': 'card:bash', 'kind': 'reward', 'detail': {'metadata': {'card_id': 'BASH', 'upgrades': 0}}},
            {'id': 'skip', 'kind': 'reward_alternative', 'label': 'Skip', 'detail': {'metadata': {}}}]
        response, info = NoncombatPolicy(self.runtime).choose(obs)
        self.assertIn(response['action_id'], ['card:bash', 'skip'])
        self.assertEqual(info['source'], 'ppo')

    def test_reward_collection_is_an_explicit_fixed_policy(self):
        obs = observation('rewards')
        obs['actions'] = [
            {'id': 'gold', 'kind': 'reward', 'detail': {'metadata': {'reward_type': 'Gold'}}},
            {'id': 'done', 'kind': 'proceed', 'detail': {'metadata': {}}}]
        response, info = NoncombatPolicy(self.runtime).choose(obs)
        self.assertEqual(response, {'action_id': 'gold'})
        self.assertEqual(info['source'], 'fixed_reward_collection')

    def test_rest_slot_means_heal_or_smith_independent_of_public_order(self):
        class PreferSmith:
            def distribution(self, obs, actions, features):
                weights = [1.0 if a['idx'] == 1 else 0.0 for a in actions]
                return weights, 0.0

        for labels in (['SMITH', 'HEAL'], ['EXTRA', 'SMITH'], ['HEAL', 'SMITH', 'EXTRA']):
            with self.subTest(labels=labels):
                obs = observation('rest')
                obs['actions'] = [{'id': f'rest:{key}', 'kind': 'rest',
                    'detail': {'metadata': {'option_key': key}}} for key in labels]
                policy = NoncombatPolicy(self.runtime)
                policy.net = PreferSmith()
                response, info = policy.choose(obs)
                self.assertEqual(response, {'action_id': 'rest:SMITH'})
                supported = [key for key in labels if key in {'HEAL', 'SMITH'}]
                self.assertEqual([a['idx'] for a in info['actions']],
                                 [{'HEAL': 0, 'SMITH': 1}[key] for key in supported])
                self.assertEqual(info['fixed_excluded_rest_options'],
                                 [key for key in labels if key == 'EXTRA'])

    def test_no_scorable_rest_candidate_stops(self):
        obs = observation('rest')
        obs['actions'] = [{'id': f'rest:{i}', 'kind': 'rest',
            'detail': {'metadata': {'option_key': f'EXTRA{i}'}}} for i in range(2)]
        with self.assertRaisesRegex(Unsupported, '休憩候補がない'):
            NoncombatPolicy(self.runtime).choose(obs)
