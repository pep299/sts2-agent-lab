from copy import deepcopy
from contextlib import redirect_stderr
from io import StringIO
from types import SimpleNamespace
import unittest

from agents.mentor.crystal import choose
from agents.mentor.noncombat import NoncombatPolicy
from agents.mentor.policy import Mentor
from sts2.observation import Unsupported
from sts2.selection import SelectionContext


def observation(tool='Big', hidden=None):
    cells = {(x, y) for y in range(3) for x in range(3)}
    hidden = cells if hidden is None else set(hidden)
    board = {'width': 3, 'height': 3, 'tool': tool, 'divinationsLeft': 3,
             'hiddenCells': [{'col': x, 'row': y} for x, y in sorted(hidden)],
             'revealedCells': [{'col': x, 'row': y} for x, y in sorted(cells - hidden)],
             'visibleItems': []}
    actions = [{'id': f'cell:{x}:{y}', 'kind': 'crystal_sphere_click',
                'detail': {'metadata': {'col': x, 'row': y}}} for x, y in sorted(hidden)]
    other = 'Small' if tool == 'Big' else 'Big'
    actions.append({'id': 'tool:' + other, 'kind': 'crystal_sphere_tool',
                    'detail': {'metadata': {'tool': other}}})
    return {'state': {'phase': 'crystal_sphere', 'crystalSphere': board}, 'actions': actions}


class PublicCrystalPolicy(unittest.TestCase):
    def test_mentor_keeps_potions_without_hiding_legal_candidates(self):
        obs = observation()
        obs['state'].update(selection=None, status={'act': 2, 'floor': 20, 'combat': None})
        obs['capabilities'] = {'gameVersion': 'v0.111.0'}
        obs['actions'] += [{'id': kind, 'kind': kind, 'detail': {'metadata': {'potion_index': 0}}}
                           for kind in ('potion', 'discard_potion')]
        original = deepcopy(obs)
        policy = Mentor.__new__(Mentor)
        policy.noncombat = NoncombatPolicy(SimpleNamespace(engine=None, net=None))
        policy.context = SelectionContext()
        with redirect_stderr(StringIO()):
            response = policy.choose({'decision_id': 1, 'observation': obs})
        self.assertEqual(response['action_id'], 'cell:1:1')
        self.assertEqual(obs, original)

    def test_big_selects_center_using_only_public_undug_cells(self):
        obs = observation()
        original = deepcopy(obs)
        response, info = choose(obs)
        self.assertEqual(response, {'action_id': 'cell:1:1'})
        self.assertEqual(info['maxNewCellsWithCurrentTool'], 9)
        self.assertFalse(info['itemVisualsUsed'])
        self.assertEqual(obs, original)

    def test_switches_to_big_only_when_it_can_open_more_hidden_cells(self):
        self.assertEqual(choose(observation('Small'))[0]['action_id'], 'tool:Big')
        obs = observation('Small', hidden={(2, 2)})
        self.assertEqual(choose(obs)[0]['action_id'], 'cell:2:2')

    def test_coverage_counts_undug_cells_and_tie_is_row_then_col(self):
        obs = observation(hidden={(0, 0), (2, 2)})
        self.assertEqual(choose(obs)[0]['action_id'], 'cell:0:0')
        obs['actions'] = list(reversed(obs['actions']))
        self.assertEqual(choose(obs)[0]['action_id'], 'cell:0:0')

    def test_does_not_invent_a_click_when_only_a_tool_is_offered(self):
        obs = observation()
        obs['actions'] = [a for a in obs['actions'] if a['kind'] == 'crystal_sphere_tool']
        with self.assertRaisesRegex(Unsupported, 'クリック候補がない'):
            choose(obs)

    def test_rejects_inconsistent_public_cells_or_illegal_action(self):
        for change in ('overlap', 'missing', 'revealed_click', 'unknown_action', 'finished'):
            with self.subTest(change=change):
                obs = observation()
                board = obs['state']['crystalSphere']
                if change == 'overlap':
                    board['revealedCells'].append({'col': 0, 'row': 0})
                elif change == 'missing':
                    board['hiddenCells'].pop()
                elif change == 'revealed_click':
                    board['hiddenCells'].remove({'col': 0, 'row': 0})
                    board['revealedCells'].append({'col': 0, 'row': 0})
                elif change == 'unknown_action':
                    obs['actions'][0]['kind'] = 'unknown'
                else:
                    board['divinationsLeft'] = 0
                with self.assertRaises(Unsupported):
                    choose(obs)


if __name__ == '__main__':
    unittest.main()
