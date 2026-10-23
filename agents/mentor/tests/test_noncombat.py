from pathlib import Path
import os
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from agents.mentor.noncombat import NoncombatPolicy
from agents.mentor.runtime import MentorRuntime, default_config


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
