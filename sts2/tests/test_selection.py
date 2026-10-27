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
            ('BIIIG_HUG', None, 'remove', None),
            ('EMPTY_CAGE', None, 'remove', None),
            ('PAELS_TOOTH', None, 'remove', None),
            ('PAELS_GROWTH', None, 'enchant', 'CLONE'),
            ('POMANDER', None, 'upgrade', None),
            ('YUMMY_COOKIE', None, 'upgrade', None),
            ('CLAWS', None, 'transform', None),
            ('SEA_GLASS', None, 'grant', None),
            ('HEFTY_TABLET', None, 'grant', None),
            ('LEAD_PAPERWEIGHT', None, 'grant', None),
            ('DOLLYS_MIRROR', None, 'copy', None),
            ('GNARLED_HAMMER', None, 'enchant', 'SHARP'),
            ('KIFUDA', None, 'enchant', 'ADROIT'),
            ('PUNCH_DAGGER', None, 'enchant', 'MOMENTUM'),
            ('ROYAL_STAMP', None, 'enchant', 'ROYALLY_APPROVED'),
            (None, 'AROMA_OF_CHAOS.pages.INITIAL.options.LET_GO', 'transform', None),
            (None, 'AROMA_OF_CHAOS.pages.INITIAL.options.MAINTAIN_CONTROL', 'upgrade', None),
            (None, 'AMALGAMATOR.pages.INITIAL.options.COMBINE_STRIKES', 'remove', None),
            (None, 'AMALGAMATOR.pages.INITIAL.options.COMBINE_DEFENDS', 'remove', None),
            (None, 'BRAIN_LEECH.pages.INITIAL.options.SHARE_KNOWLEDGE', 'grant', None),
            (None, 'DOORS_OF_LIGHT_AND_DARK.pages.INITIAL.options.DARK', 'remove', None),
            (None, 'ENDLESS_CONVEYOR.pages.ALL.options.JELLY_LIVER', 'transform', None),
            (None, 'FIELD_OF_MAN_SIZED_HOLES.pages.INITIAL.options.RESIST', 'remove', None),
            (None, 'FIELD_OF_MAN_SIZED_HOLES.pages.INITIAL.options.ENTER_YOUR_HOLE', 'enchant', 'PERFECT_FIT'),
            (None, 'LUMINOUS_CHOIR.pages.INITIAL.options.REACH_INTO_THE_FLESH', 'remove', None),
            (None, 'MORPHIC_GROVE.pages.INITIAL.options.GROUP', 'transform', None),
            (None, 'ROOM_FULL_OF_CHEESE.pages.INITIAL.options.GORGE', 'grant', None),
            (None, 'SAPPHIRE_SEED.pages.INITIAL.options.EAT', 'upgrade', None),
            (None, 'SAPPHIRE_SEED.pages.INITIAL.options.PLANT', 'enchant', 'SOWN'),
            (None, 'TRIAL.pages.MERCHANT.options.INNOCENT', 'upgrade', None),
            (None, 'TRIAL.pages.NONDESCRIPT.options.INNOCENT', 'transform', None),
            (None, 'SPIRALING_WHIRLPOOL.pages.INITIAL.options.OBSERVE', 'enchant', 'SPIRAL'),
            (None, 'STONE_OF_ALL_TIME.pages.INITIAL.options.PUSH', 'enchant', 'VIGOROUS'),
            (None, 'WATERLOGGED_SCRIPTORIUM.pages.INITIAL.options.TENTACLE_QUILL', 'enchant', 'STEADY'),
            (None, 'WATERLOGGED_SCRIPTORIUM.pages.INITIAL.options.PRICKLY_SPONGE', 'enchant', 'STEADY'),
            (None, 'WELLSPRING.pages.INITIAL.options.BATHE', 'remove', None),
            (None, 'ZEN_WEAVER.pages.INITIAL.options.EMOTIONAL_AWARENESS', 'remove', None),
            (None, 'ZEN_WEAVER.pages.INITIAL.options.ARACHNID_ACUPUNCTURE', 'remove', None),
            (None, 'SELF_HELP_BOOK.pages.INITIAL.options.READ_ENTIRE_BOOK', 'enchant', 'SWIFT'),
            (None, 'GRAVE_OF_THE_FORGOTTEN.pages.INITIAL.options.CONFRONT', 'enchant', 'SOULS_POWER')]
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

    def test_relic_rewards_treasure_and_shop_keep_public_parent_effect(self):
        for kind, meta in [('reward', {'relic_id': 'RELIC.POMANDER'}),
                           ('claim_relic', {'relic_id': 'POMANDER'}),
                           ('buy', {'entry_type': 'MerchantRelicEntry', 'item_id': 'POMANDER'})]:
            with self.subTest(kind=kind):
                context = SelectionContext()
                context.remember({'state': {'phase': 'rewards'}, 'actions': [
                    {'id': 'take', 'kind': kind, 'detail': {'metadata': meta}}]}, {'action_id': 'take'})
                prepared = context.prepare(selection())['state']['selection']
                self.assertEqual(prepared['purpose'], 'upgrade')
                self.assertEqual(prepared['parentRelic'], 'POMANDER')

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
