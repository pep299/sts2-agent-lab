"""公開した親行動から、続くカード選択の効果を保持する。"""

from copy import deepcopy

from sts2.observation import entry


RELIC_SELECTIONS = {
    'NEW_LEAF': ('transform', None), 'ASTROLABE': ('transform', None),
    'PRESERVED_FOG': ('remove', None), 'PRECARIOUS_SHEARS': ('remove', None),
    'PRECISE_SCISSORS': ('remove', None), 'BIIIG_HUG': ('remove', None),
    'EMPTY_CAGE': ('remove', None), 'PAELS_TOOTH': ('remove', None),
    'POMANDER': ('upgrade', None), 'YUMMY_COOKIE': ('upgrade', None),
    'TRI_BOOMERANG': ('enchant', 'INSTINCT'), 'ELECTRIC_SHRYMP': ('enchant', 'IMBUED'),
    'PAELS_GROWTH': ('enchant', 'CLONE'), 'CLAWS': ('transform', None),
    'SEA_GLASS': ('grant', None), 'HEFTY_TABLET': ('grant', None),
    'LEAD_PAPERWEIGHT': ('grant', None),
}


class SelectionContext:
    def __init__(self):
        self.reset()

    def reset(self):
        self.selection_purpose = None
        self.selection_enchantment = None
        self.parent_relic = None

    def prepare(self, observation):
        state = observation['state']
        if not state.get('selection'):
            return observation
        obs = deepcopy(observation)
        selection = obs['state']['selection']
        if not selection.get('purpose'):
            if self.selection_purpose:
                selection['purpose'] = self.selection_purpose
            elif state['status']['combat'] is not None:
                selection['purpose'] = 'combat_choice'
            else:
                selection['purpose'] = None
        if not selection.get('enchantment'):
            selection['enchantment'] = self.selection_enchantment
        if self.parent_relic:
            selection['parentRelic'] = self.parent_relic
        return obs

    def remember(self, observation, response):
        if observation['state']['phase'] == 'grid_selection':
            return
        self.selection_purpose = None
        self.selection_enchantment = None
        self.parent_relic = None
        action = next(a for a in observation['actions'] if a['id'] == response['action_id'])
        detail = action['detail']
        meta = detail['metadata']
        relic = meta.get('relic_id')
        if action['kind'] == 'buy' and meta.get('entry_type') == 'MerchantRelicEntry':
            relic = meta.get('item_id')
        if action['kind'] == 'event':
            option = next(o for o in observation['state']['options'] if o['index'] == meta['option_index'])
            relic = option.get('relic')
        if relic:
            self.parent_relic = entry(relic)
            self.selection_purpose, self.selection_enchantment = RELIC_SELECTIONS.get(self.parent_relic, (None, None))
        if action['kind'] == 'rest' and meta.get('option_key') == 'SMITH':
            self.selection_purpose = 'upgrade'
        elif action['kind'] == 'buy' and meta.get('entry_type') == 'MerchantCardRemovalEntry':
            self.selection_purpose = 'remove'
        elif action['kind'] == 'event':
            index = meta['option_index']
            option = next(o for o in observation['state']['options'] if o['index'] == index)
            key = option.get('text_key')
            purposes = {'AROMA_OF_CHAOS.pages.INITIAL.options.LET_GO': 'transform',
                        'AROMA_OF_CHAOS.pages.INITIAL.options.MAINTAIN_CONTROL': 'upgrade',
                        'AMALGAMATOR.pages.INITIAL.options.COMBINE_STRIKES': 'remove',
                        'AMALGAMATOR.pages.INITIAL.options.COMBINE_DEFENDS': 'remove',
                        'BRAIN_LEECH.pages.INITIAL.options.SHARE_KNOWLEDGE': 'grant',
                        'DOORS_OF_LIGHT_AND_DARK.pages.INITIAL.options.DARK': 'remove',
                        'ENDLESS_CONVEYOR.pages.ALL.options.JELLY_LIVER': 'transform',
                        'FIELD_OF_MAN_SIZED_HOLES.pages.INITIAL.options.RESIST': 'remove',
                        'LUMINOUS_CHOIR.pages.INITIAL.options.REACH_INTO_THE_FLESH': 'remove',
                        'MORPHIC_GROVE.pages.INITIAL.options.GROUP': 'transform',
                        'ROOM_FULL_OF_CHEESE.pages.INITIAL.options.GORGE': 'grant',
                        'SAPPHIRE_SEED.pages.INITIAL.options.EAT': 'upgrade',
                        'TRIAL.pages.MERCHANT.options.INNOCENT': 'upgrade',
                        'TRIAL.pages.NONDESCRIPT.options.INNOCENT': 'transform',
                        'WELLSPRING.pages.INITIAL.options.BATHE': 'remove',
                        'ZEN_WEAVER.pages.INITIAL.options.EMOTIONAL_AWARENESS': 'remove',
                        'ZEN_WEAVER.pages.INITIAL.options.ARACHNID_ACUPUNCTURE': 'remove',
                        'WOOD_CARVINGS.pages.INITIAL.options.BIRD': 'transform',
                        'WOOD_CARVINGS.pages.INITIAL.options.TORUS': 'transform',
                        'SYMBIOTE.pages.INITIAL.options.KILL_WITH_FIRE': 'transform',
                        'WHISPERING_HOLLOW.pages.INITIAL.options.HUG': 'transform',
                        'SPIRIT_GRAFTER.pages.INITIAL.options.REJECTION': 'upgrade'}
            if key in purposes:
                self.selection_purpose = purposes[key]
            books = {'SELF_HELP_BOOK.pages.INITIAL.options.READ_THE_BACK': 'SHARP',
                     'SELF_HELP_BOOK.pages.INITIAL.options.READ_PASSAGE': 'NIMBLE',
                     'SELF_HELP_BOOK.pages.INITIAL.options.READ_ENTIRE_BOOK': 'SWIFT',
                     'FIELD_OF_MAN_SIZED_HOLES.pages.INITIAL.options.ENTER_YOUR_HOLE': 'PERFECT_FIT',
                     'SAPPHIRE_SEED.pages.INITIAL.options.PLANT': 'SOWN',
                     'SPIRALING_WHIRLPOOL.pages.INITIAL.options.OBSERVE': 'SPIRAL',
                     'STONE_OF_ALL_TIME.pages.INITIAL.options.PUSH': 'VIGOROUS',
                     'WATERLOGGED_SCRIPTORIUM.pages.INITIAL.options.TENTACLE_QUILL': 'STEADY',
                     'WATERLOGGED_SCRIPTORIUM.pages.INITIAL.options.PRICKLY_SPONGE': 'STEADY',
                     'WOOD_CARVINGS.pages.INITIAL.options.SNAKE': 'SLITHER',
                     'GRAVE_OF_THE_FORGOTTEN.pages.INITIAL.options.CONFRONT': 'SOULS_POWER',
                     'SYMBIOTE.pages.INITIAL.options.APPROACH': 'CORRUPTED'}
            if key in books:
                self.selection_purpose = 'enchant'
                self.selection_enchantment = books[key]
