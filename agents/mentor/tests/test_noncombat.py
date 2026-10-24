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

    def test_ancient_relic_offers_reach_the_trained_relic_candidates(self):
        runtime = self.runtime

        class RecordingNet:
            def distribution(self, obs, actions, features):
                self.obs, self.actions = obs, actions
                return runtime.net.distribution(obs, actions, features)

        relics = ['YUMMY_COOKIE', 'BIIIG_HUG', 'SEAL_OF_GOLD']
        for event_id in ('OROBAS', 'PAEL', 'TEZCATARA', 'NONUPEIPE', 'TANX', 'VAKUU'):
            for offered in (relics, list(reversed(relics))):
                with self.subTest(event_id=event_id, offered=offered):
                    obs = observation('event')
                    obs['state'].update(eventId=event_id, options=[
                        {'index': index, 'relic': relic, 'title': None, 'description': None,
                         'text_key': f'{event_id}.pages.INITIAL.options.{relic}'}
                        for index, relic in zip((9, 3, 7), offered)])
                    obs['actions'] = [{'id': f'event:{index}', 'kind': 'event',
                        'detail': {'metadata': {'option_index': index}}} for index in (9, 3, 7)]
                    policy = NoncombatPolicy(runtime)
                    policy.net = RecordingNet()
                    response, info = policy.choose(obs)
                    self.assertEqual(policy.net.obs['boss_relic_options'], offered)
                    self.assertEqual(policy.net.actions,
                                     [{'action': 'pick_boss_relic', 'idx': i} for i in range(3)])
                    self.assertEqual(response['action_id'], obs['actions'][info['chosen']]['id'])

    def test_ordinary_relic_event_keeps_its_event_surface(self):
        obs = observation('event')
        obs['state'].update(eventId='RELIC_TRADER', options=[
            {'index': index, 'relic': relic, 'title': None, 'description': None,
             'text_key': f'RELIC_TRADER.pages.INITIAL.options.{index}'}
            for index, relic in enumerate(('YUMMY_COOKIE', 'BIIIG_HUG'))])
        obs['actions'] = [{'id': f'event:{index}', 'kind': 'event',
            'detail': {'metadata': {'option_index': index}}} for index in range(2)]
        response, info = NoncombatPolicy(self.runtime).choose(obs)
        self.assertEqual(info['actions'], [{'action': 'event_choice', 'idx': i} for i in range(2)])
        self.assertIn(response['action_id'], ('event:0', 'event:1'))

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
