from pathlib import Path
import sys
import unittest
from contextlib import redirect_stderr
from io import StringIO

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from agents.mentor.combat import Unsupported
from agents.mentor.policy import Mentor
from agents.mentor.noncombat import reward_claims


def base():
    return {'state': {'phase': 'map', 'status': {'combat': None}, 'selection': None}, 'actions': []}


class PolicyContract(unittest.TestCase):
    def test_selection_fallback_is_opt_in_and_obeys_public_limits(self):
        policy = Mentor.__new__(Mentor)
        policy.selection_fallback = False
        policy.last_signature = None
        policy.repeated_decisions = 0
        obs = base()
        obs['state'].update(phase='grid_selection', selection={'min': 2, 'max': 3, 'cards': [{}, {}, {}]})
        obs['actions'] = [{'id': 'choose_cards:', 'detail': {'parameter': 'cardIndices'}}]
        boundary = {'decision_id': 9, 'observation': obs}
        with self.assertRaises(Unsupported):
            policy.fallback_selection(boundary, Unsupported('unknown purpose'))
        policy.selection_fallback = True
        with redirect_stderr(StringIO()):
            self.assertEqual(policy.fallback_selection(boundary, Unsupported('unknown purpose'))['indices'], [0, 1])
            obs['state']['selection']['min'] = 0
            self.assertEqual(policy.fallback_selection(boundary, Unsupported('unknown purpose'))['indices'], [])
        obs['state']['phase'] = 'combat'
        with self.assertRaises(Unsupported):
            policy.fallback_selection(boundary, Unsupported('missing combat effect'))


    def test_full_potion_belt_skips_potion_but_keeps_card_reward(self):
        obs = base()
        obs['state']['status']['potionBelt'] = {'slots': [{'potion': {'id': 'X'}}]}
        actions = [{'id': kind, 'kind': 'reward', 'detail': {'metadata': {'reward_type': kind}}}
                   for kind in ('Potion', 'Card')]
        self.assertEqual([a['id'] for a in reward_claims(obs, actions)], ['Card'])
        obs['state']['status']['potionBelt']['slots'][0]['potion'] = None
        self.assertEqual([a['id'] for a in reward_claims(obs, actions)], ['Potion', 'Card'])


    def test_declining_one_card_reward_keeps_the_other(self):
        obs = base()
        obs['state']['status']['potionBelt'] = {'slots': [{'potion': None}]}
        actions = [{'id': f'choose_reward:{i}:Card', 'kind': 'reward',
                    'detail': {'metadata': {'reward_type': 'Card'}}} for i in range(2)]
        self.assertEqual([a['id'] for a in reward_claims(obs, actions, {actions[0]['id']})],
                         [actions[1]['id']])
