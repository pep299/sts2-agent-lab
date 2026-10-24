from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from backends.learn_dll.observation import normalize_observation


def base():
    return {'state': {'phase': 'map', 'status': {'combat': None, 'map': {
        'nodes': [{'coord': {'row': 1, 'col': 3}, 'roomType': 'Monster'}]}},
        'options': [], 'selection': None}, 'actions': []}


class LearnContract(unittest.TestCase):

    def test_map_keeps_native_index_and_public_destination(self):
        obs = base()
        obs['actions'] = [{'id': 'map:1:3', 'kind': 'map', 'detail': {
            'nativeKind': 'MoveTo', 'nativeOptionIndex': 7}}]
        original = deepcopy(obs)
        result = normalize_observation(obs)['actions'][0]
        self.assertEqual(result['detail']['metadata'], {'row': 1, 'col': 3, 'room_type': 'Monster'})
        self.assertNotIn('nativeOptionIndex', result['detail'])
        self.assertNotIn('nativeKind', result['detail'])
        self.assertEqual(obs, original)

    def test_enemy_id_does_not_become_a_slot(self):
        obs = base()
        obs['actions'] = [{'id': 'play:2:42', 'kind': 'play', 'detail': {
            'nativeKind': 'PlayCard', 'nativeOptionIndex': 9, 'handIndex': 2, 'target': 42}}]
        meta = normalize_observation(obs)['actions'][0]['detail']['metadata']
        self.assertEqual(meta, {'card_index': 2, 'target_id': 42})

    def test_gold_reward_is_not_a_card_reward(self):
        obs = base()
        obs['state']['rewards'] = {'rewards': [{'taken': False, 'cards': None, 'potionId': None,
                                             'gold': 12, 'relicId': None}]}
        obs['actions'] = [{'id': 'dll:0', 'kind': 'reward', 'detail': {
            'nativeKind': 'TakeReward', 'cardDetails': None}}]
        action = normalize_observation(obs)['actions'][0]
        self.assertNotIn('nativeKind', action['detail'])
        self.assertEqual(action['detail']['metadata']['reward_type'], 'Gold')


    def test_combat_selection_is_sent_to_replay_instead_of_ppo(self):
        obs = base()
        obs['state'].update(phase='grid_selection', selection={'min': 1, 'max': 1})
        obs['state']['status']['combat'] = {'turn': 2}
        obs['actions'] = [{'id': 'dll:0', 'kind': 'select_grid', 'detail': {'nativeKind': 'SelectCards'}},
                          {'id': 'dll:select_cards', 'kind': 'select_grid', 'detail': {
                              'nativeKind': 'SelectCards', 'parameter': 'cardIndices'}}]
        result = normalize_observation(obs)
        self.assertEqual([a['id'] for a in result['actions']], ['choose_cards:'])
        self.assertEqual(result['state']['selection']['min'], 1)


class RewardAlternativeContract(unittest.TestCase):
    def test_proceed_is_skip_only_while_individual_card_rewards_are_offered(self):
        obs = base()
        obs['state']['phase'] = 'rewards'
        obs['actions'] = [
            {'id': 'card:0', 'kind': 'reward', 'detail': {'nativeKind': 'TakeReward',
                'cardDetails': {'state': {'id': 'BASH', 'upgrade': 0}}}},
            {'id': 'done', 'kind': 'reward_alternative', 'detail': {'nativeKind': 'ProceedFromRewards'}}]
        result = normalize_observation(obs)
        self.assertEqual((result['actions'][1]['kind'], result['actions'][1]['label']), ('reward_alternative', 'Skip'))
        obs['actions'].pop(0)
        result = normalize_observation(obs)
        self.assertEqual(result['actions'][0]['kind'], 'proceed')


if __name__ == '__main__':
    unittest.main()
