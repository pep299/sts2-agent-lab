import base64
from copy import deepcopy
import gzip
import unittest

from agents.mentor.crystal import choose
from agents.mentor.crystal_vision import CELL, SHAPES, recognize
from sts2.observation import Unsupported


def encoded(pixels):
    return base64.b64encode(gzip.compress(pixels)).decode()


def scene(*, hidden, placements):
    templates, cells = [], {}
    for number, (kind, (w, h)) in enumerate(SHAPES.items(), 1):
        artwork = {(x, y): bytes([number * 20, x * 40, y * 40, 255]) * (CELL * CELL)
                   for y in range(h) for x in range(w)}
        pixels = b''.join(artwork[x, y][py * CELL * 4:(py + 1) * CELL * 4]
                          for y in range(h) for py in range(CELL) for x in range(w))
        templates.append(dict(kind=kind, widthCells=w, heightCells=h, width=w * CELL,
                              height=h * CELL, rgbaGzipBase64=encoded(pixels)))
        cells[kind] = artwork
    revealed = {(x, y) for y in range(5) for x in range(5)} - hidden
    fragments = []
    for x, y in sorted(revealed):
        pixels = bytes(CELL * CELL * 4)
        for kind, left, top in placements:
            pixels = cells[kind].get((x - left, y - top), pixels)
        fragments.append(dict(col=x, row=y, width=CELL, height=CELL, rgbaGzipBase64=encoded(pixels)))
    board = dict(width=5, height=5, tool='Big', divinationsLeft=3,
                 hiddenCells=[dict(col=x, row=y) for x, y in sorted(hidden)],
                 revealedCells=[dict(col=x, row=y) for x, y in sorted(revealed)],
                 visibleFragments=fragments, visualTemplates=templates)
    actions = [dict(id=f'cell:{x}:{y}', kind='crystal_sphere_click',
                    detail=dict(metadata=dict(col=x, row=y))) for x, y in sorted(hidden)]
    actions.append(dict(id='tool:Small', kind='crystal_sphere_tool', detail=dict(metadata=dict(tool='Small'))))
    return dict(state=dict(crystalSphere=board), actions=actions), revealed


class PublicImageRecognition(unittest.TestCase):
    def test_visible_curse_changes_tool_choice_while_reward_is_completed(self):
        obs, _ = scene(hidden={(1, 1), (2, 1)}, placements=[('curse', 0, 0), ('gold_big', 2, 1)])
        response, info = choose(obs)
        self.assertEqual(response['action_id'], 'tool:Small')
        self.assertTrue(info['itemVisualsUsed'])
        self.assertEqual({r['kinds'][0] for r in info['vision']['recognized']}, {'curse', 'gold_big'})
        obs['state']['crystalSphere']['tool'] = 'Small'
        obs['actions'][-1] = dict(id='tool:Big', kind='crystal_sphere_tool', detail=dict(metadata=dict(tool='Big')))
        self.assertEqual(choose(obs)[0]['action_id'], 'cell:2:1')
        # 同じ開閉状態でも呪いの可視画素を消すと、画像未使用の基準と同じBigへ変わる。
        for fragment in obs['state']['crystalSphere']['visibleFragments']:
            if fragment['col'] < 2 and fragment['row'] < 2:
                fragment['rgbaGzipBase64'] = encoded(bytes(CELL * CELL * 4))
        self.assertEqual(choose(obs)[0]['action_id'], 'tool:Big')

    def test_partial_reward_art_changes_click_and_hidden_metadata_is_ignored(self):
        hidden = {(x, y) for y in range(5) for x in range(5)} - {(3, 4)}
        obs, _ = scene(hidden=hidden, placements=[('gold_big', 3, 4)])
        response, info = choose(obs)
        self.assertEqual(response['action_id'], 'cell:3:3')
        self.assertEqual(info['vision']['recognized'][0]['remainingCells'], 1)
        private_variant = deepcopy(obs)
        private_variant['state']['crystalSphere']['Items'] = [{'type': 'curse', 'position': [0, 0]}]
        self.assertEqual(choose(private_variant), (response, info))
        obs['state']['crystalSphere']['visibleFragments'][0]['rgbaGzipBase64'] = encoded(bytes(CELL * CELL * 4))
        self.assertEqual(choose(obs)[0]['action_id'], 'cell:1:1')

    def test_ambiguous_art_does_not_become_a_certain_item(self):
        obs, revealed = scene(hidden={(x, y) for y in range(5) for x in range(5)} - {(2, 2)},
                              placements=[('card_common', 2, 2)])
        board = obs['state']['crystalSphere']
        curse = next(t for t in board['visualTemplates'] if t['kind'] == 'curse')
        common = next(t for t in board['visualTemplates'] if t['kind'] == 'card_common')
        curse['rgbaGzipBase64'] = common['rgbaGzipBase64']
        items, info = recognize(board, revealed)
        self.assertEqual(items, [])
        self.assertEqual(info['ambiguousOrUnknownCells'], 1)

    def test_missing_dictionary_or_bad_public_crops_are_explicit(self):
        obs, revealed = scene(hidden={(1, 1)}, placements=[])
        board = obs['state']['crystalSphere']
        board['visibleFragments'].pop()
        with self.assertRaisesRegex(Unsupported, '欠落'):
            recognize(board, revealed)
        board.pop('visualTemplates')
        self.assertEqual(recognize(board, revealed)[1]['reason'], 'public_visual_templates_unavailable')


if __name__ == '__main__':
    unittest.main()
