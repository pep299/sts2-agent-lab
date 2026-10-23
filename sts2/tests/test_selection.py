from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from sts2.selection import SelectionContext


def selection(combat=None):
    return {'state': {'phase': 'grid_selection', 'status': {'combat': combat},
                      'selection': {'min': 1, 'max': 1, 'cards': [{}]}}}


class SelectionKnowledge(unittest.TestCase):
    def test_known_parent_effects_fill_missing_public_selection_purpose(self):
        cases = [
            ('PRECARIOUS_SHEARS', None, 'remove', None),
            ('TRI_BOOMERANG', None, 'enchant', 'INSTINCT'),
            (None, 'AROMA_OF_CHAOS.pages.INITIAL.options.LET_GO', 'transform', None),
            (None, 'AROMA_OF_CHAOS.pages.INITIAL.options.MAINTAIN_CONTROL', 'upgrade', None),
            (None, 'SELF_HELP_BOOK.pages.INITIAL.options.READ_ENTIRE_BOOK', 'enchant', 'SWIFT')]
        for relic, key, purpose, enchantment in cases:
            with self.subTest(relic=relic, key=key):
                context = SelectionContext()
                parent = {'state': {'phase': 'event', 'options': [{'index': 2, 'relic': relic, 'text_key': key}]},
                          'actions': [{'id': 'event:2', 'kind': 'event', 'detail': {'metadata': {'option_index': 2}}}]}
                context.remember(parent, {'action_id': 'event:2'})
                before = selection()
                original = deepcopy(before)
                prepared = context.prepare(before)['state']['selection']
                self.assertEqual((prepared['purpose'], prepared['enchantment']), (purpose, enchantment))
                self.assertEqual(before, original)

    def test_explicit_purpose_is_preserved(self):
        before = selection()
        before['state']['selection']['purpose'] = 'remove'
        self.assertEqual(SelectionContext().prepare(before)['state']['selection']['purpose'], 'remove')

    def test_unknown_effect_does_not_guess_from_cards(self):
        self.assertIsNone(SelectionContext().prepare(selection())['state']['selection']['purpose'])

    def test_combat_selection_is_identified_without_guessing_effect(self):
        self.assertEqual(SelectionContext().prepare(selection({'turn': 2}))['state']['selection']['purpose'], 'combat_choice')

    def test_run_reset_discards_parent_memory(self):
        context = SelectionContext()
        context.remember({'state': {'phase': 'rest'}, 'actions': [
            {'id': 'rest:smith', 'kind': 'rest', 'detail': {'metadata': {'option_key': 'SMITH'}}}]},
            {'action_id': 'rest:smith'})
        self.assertEqual(context.prepare(selection())['state']['selection']['purpose'], 'upgrade')
        context.reset()
        self.assertIsNone(context.prepare(selection())['state']['selection']['purpose'])
