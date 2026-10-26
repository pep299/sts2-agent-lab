from copy import deepcopy
import unittest

from agents.mentor.crystal import choose, infer_items
from sts2.observation import Unsupported


def observation(hidden, true_map, size=5):
    revealed = {(x, y) for y in range(size) for x in range(size)} - hidden
    board = dict(width=size, height=size, tool='Big', divinationsLeft=3,
        hiddenCells=[dict(col=x, row=y) for x, y in sorted(hidden)],
        revealedCells=[dict(col=x, row=y, content=true_map.get((x, y), 'empty')) for x, y in sorted(revealed)])
    actions = [dict(id=f'cell:{x}:{y}', kind='crystal_sphere_click',
                    detail=dict(metadata=dict(col=x, row=y))) for x, y in sorted(hidden)]
    actions.append(dict(id='tool:Small', kind='crystal_sphere_tool', detail=dict(metadata=dict(tool='Small'))))
    return dict(state=dict(crystalSphere=board), actions=actions), revealed


class PublicCellContents(unittest.TestCase):
    def test_known_curse_changes_tool_and_reward_can_be_completed(self):
        contents = {(x, y): 'curse' for y in (0, 1) for x in (0, 1)}
        contents.update({(x, y): 'card_reward' for y in (0, 1) for x in (2, 3)})
        obs, _ = observation({(1, 1), (2, 1)}, contents)
        response, info = choose(obs)
        self.assertEqual(response['action_id'], 'tool:Small')
        self.assertEqual({r['kind'] for r in info['inference']['inferredItems']}, {'curse', 'card_reward'})
        obs['state']['crystalSphere']['tool'] = 'Small'
        obs['actions'][-1] = dict(id='tool:Big', kind='crystal_sphere_tool', detail=dict(metadata=dict(tool='Big')))
        self.assertEqual(choose(obs)[0]['action_id'], 'cell:2:1')
        for cell in obs['state']['crystalSphere']['revealedCells']:
            if cell['content'] == 'curse':
                cell['content'] = 'empty'
        self.assertEqual(choose(obs)[0]['action_id'], 'tool:Big')

    def test_hidden_world_changes_do_not_reach_input_or_decision(self):
        hidden = {(x, y) for y in range(5) for x in range(5)} - {(3, 4)}
        obs, _ = observation(hidden, {(3, 4): 'relic', (4, 4): 'relic'})
        changed, _ = observation(hidden, {(3, 4): 'relic', (4, 4): 'curse', (0, 0): 'gold'})
        self.assertEqual(obs, changed)
        self.assertEqual(choose(obs), choose(changed))
        extra = deepcopy(obs)
        extra['state']['crystalSphere']['Items'] = [{'kind': 'curse', 'position': [0, 0]}]
        self.assertEqual(choose(obs), choose(extra))

    def test_single_gold_or_potion_does_not_reveal_size_or_position(self):
        hidden = {(x, y) for y in range(5) for x in range(5)} - {(2, 2)}
        for kind in ('gold', 'potion'):
            with self.subTest(kind=kind):
                obs, revealed = observation(hidden, {(2, 2): kind})
                items, info = infer_items(obs['state']['crystalSphere'], revealed)
                self.assertEqual(items, [])
                self.assertEqual(info['ambiguousOrUnknownCells'], 1)

    def test_adjacent_same_type_cells_are_not_merged_as_one_item(self):
        obs, revealed = observation(set(), {(1, 1): 'gold', (2, 1): 'gold'})
        items, _ = infer_items(obs['state']['crystalSphere'], revealed)
        self.assertEqual(items, [])

    def test_unknown_opened_content_is_not_treated_as_empty(self):
        obs, _ = observation({(1, 1)}, {(2, 2): 'unknown'})
        with self.assertRaisesRegex(Unsupported, '公開セル内容'):
            choose(obs)


if __name__ == '__main__':
    unittest.main()
