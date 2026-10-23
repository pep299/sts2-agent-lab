from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from combat import Unsupported
from learn_observation import LearnObservation


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
        result = LearnObservation().normalize(obs)['actions'][0]
        self.assertEqual(result['detail']['metadata'], {'row': 1, 'col': 3, 'room_type': 'Monster'})
        self.assertEqual(result['detail']['nativeOptionIndex'], 7)
        self.assertEqual(obs, original)

    def test_enemy_id_does_not_become_a_slot(self):
        obs = base()
        obs['actions'] = [{'id': 'play:2:42', 'kind': 'play', 'detail': {
            'nativeKind': 'PlayCard', 'nativeOptionIndex': 9, 'handIndex': 2, 'target': 42}}]
        meta = LearnObservation().normalize(obs)['actions'][0]['detail']['metadata']
        self.assertEqual(meta, {'card_index': 2, 'target_id': 42})

    def test_gold_reward_is_not_a_card_reward(self):
        obs = base()
        obs['state']['rewards'] = {'rewards': [{'taken': False, 'cards': None, 'potionId': None,
                                             'gold': 12, 'relicId': None}]}
        obs['actions'] = [{'id': 'dll:0', 'kind': 'reward', 'detail': {
            'nativeKind': 'TakeReward', 'cardDetails': None}}]
        action = LearnObservation().normalize(obs)['actions'][0]
        self.assertEqual(action['detail']['nativeKind'], 'CollectReward')
        self.assertEqual(action['detail']['metadata']['reward_type'], 'Gold')

    def test_unknown_noncombat_selection_does_not_guess_purpose(self):
        obs = base()
        obs['state'].update(phase='grid_selection', selection={'min': 1, 'max': 1})
        with self.assertRaises(Unsupported):
            LearnObservation().normalize(obs)

    def test_combat_selection_is_sent_to_replay_instead_of_ppo(self):
        obs = base()
        obs['state'].update(phase='grid_selection', selection={'min': 1, 'max': 1})
        obs['state']['status']['combat'] = {'turn': 2}
        obs['actions'] = [{'id': 'dll:0', 'kind': 'select_grid', 'detail': {'nativeKind': 'SelectCards'}},
                          {'id': 'dll:select_cards', 'kind': 'select_grid', 'detail': {
                              'nativeKind': 'SelectCards', 'parameter': 'cardIndices'}}]
        result = LearnObservation().normalize(obs)
        self.assertEqual([a['id'] for a in result['actions']], ['choose_cards:'])
        self.assertEqual(result['state']['selection']['purpose'], 'combat_choice')

    def test_smith_parent_supplies_selection_purpose(self):
        obs = base()
        obs['actions'] = [{'id': 'dll:1', 'kind': 'rest', 'detail': {
            'nativeKind': 'ChooseRestOption', 'restOptionId': 'SMITH'}}]
        adapter = LearnObservation()
        adapter.remember(adapter.normalize(obs), {'action_id': 'dll:1'})
        obs['state'].update(phase='grid_selection', selection={'min': 1, 'max': 1})
        obs['actions'] = []
        self.assertEqual(adapter.normalize(obs)['state']['selection']['purpose'], 'upgrade')


    def test_event_selection_carries_the_declared_enchantment(self):
        obs = base()
        obs['state']['phase'] = 'event'
        obs['state']['options'] = [{'index': 2, 'relicId': None,
            'textKey': 'SELF_HELP_BOOK.pages.INITIAL.options.READ_ENTIRE_BOOK'}]
        obs['actions'] = [{'id': 'event:2', 'kind': 'event', 'detail': {
            'nativeKind': 'ChooseEventOption', 'eventOptionIndex': 2}}]
        adapter = LearnObservation()
        adapter.remember(adapter.normalize(obs), {'action_id': 'event:2'})
        obs['state'].update(phase='grid_selection', selection={'min': 1, 'max': 1})
        obs['actions'] = []
        selection = adapter.normalize(obs)['state']['selection']
        self.assertEqual((selection['purpose'], selection['enchantment']), ('enchant', 'SWIFT'))

    def test_aroma_event_distinguishes_transform_and_upgrade(self):
        for key, purpose in [('LET_GO', 'transform'), ('MAINTAIN_CONTROL', 'upgrade')]:
            with self.subTest(key=key):
                obs = base()
                obs['state']['phase'] = 'event'
                obs['state']['options'] = [{'index': 0, 'relicId': None,
                    'textKey': f'AROMA_OF_CHAOS.pages.INITIAL.options.{key}'}]
                obs['actions'] = [{'id': 'event:0', 'kind': 'event', 'detail': {
                    'nativeKind': 'ChooseEventOption', 'eventOptionIndex': 0}}]
                adapter = LearnObservation()
                adapter.remember(adapter.normalize(obs), {'action_id': 'event:0'})
                obs['state'].update(phase='grid_selection', selection={'min': 1, 'max': 1})
                obs['actions'] = []
                self.assertEqual(adapter.normalize(obs)['state']['selection']['purpose'], purpose)

    def test_precarious_shears_supplies_removal_purpose_and_keeps_two_picks(self):
        obs = base()
        obs['state']['phase'] = 'event'
        obs['state']['options'] = [{'index': 0, 'relicId': 'PRECARIOUS_SHEARS',
                                  'textKey': 'NEOW.pages.INITIAL.options.PRECARIOUS_SHEARS'}]
        obs['actions'] = [{'id': 'event:0', 'kind': 'event', 'detail': {'nativeKind': 'ChooseEventOption', 'eventOptionIndex': 0}}]
        adapter = LearnObservation()
        adapter.remember(adapter.normalize(obs), {'action_id': 'event:0'})
        obs['state'].update(phase='grid_selection', selection={'min': 2, 'max': 2})
        obs['actions'] = []
        selected = adapter.normalize(obs)['state']['selection']
        self.assertEqual((selected['purpose'], selected['min'], selected['max']), ('remove', 2, 2))

class RewardAlternativeContract(unittest.TestCase):
    def test_proceed_is_skip_only_while_individual_card_rewards_are_offered(self):
        obs = base()
        obs['state']['phase'] = 'rewards'
        obs['actions'] = [
            {'id': 'card:0', 'kind': 'reward', 'detail': {'nativeKind': 'TakeReward',
                'cardDetails': {'state': {'id': 'BASH', 'upgrade': 0}}}},
            {'id': 'done', 'kind': 'reward_alternative', 'detail': {'nativeKind': 'ProceedFromRewards'}}]
        result = LearnObservation().normalize(obs)
        self.assertEqual((result['actions'][1]['kind'], result['actions'][1]['label']), ('reward_alternative', 'Skip'))
        obs['actions'].pop(0)
        result = LearnObservation().normalize(obs)
        self.assertEqual(result['actions'][0]['kind'], 'proceed')


if __name__ == '__main__':
    unittest.main()
