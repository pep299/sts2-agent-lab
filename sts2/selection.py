"""公開した親行動から、続くカード選択の効果を保持する。"""

from copy import deepcopy

from sts2.observation import Unsupported, entry


class SelectionContext:
    def __init__(self):
        self.reset()

    def reset(self):
        self.selection_purpose = None
        self.selection_enchantment = None

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
                raise Unsupported('公開選択の目的がなく、直前の公開行動からも特定できない')
        if not selection.get('enchantment'):
            selection['enchantment'] = self.selection_enchantment
        return obs

    def remember(self, observation, response):
        if observation['state']['phase'] == 'grid_selection':
            return
        self.selection_purpose = None
        self.selection_enchantment = None
        action = next(a for a in observation['actions'] if a['id'] == response['action_id'])
        detail = action['detail']
        meta = detail['metadata']
        if action['kind'] == 'rest' and meta.get('option_key') == 'SMITH':
            self.selection_purpose = 'upgrade'
        elif action['kind'] == 'buy' and meta.get('entry_type') == 'MerchantCardRemovalEntry':
            self.selection_purpose = 'remove'
        elif action['kind'] == 'event':
            index = meta['option_index']
            option = next(o for o in observation['state']['options'] if o['index'] == index)
            # 公開レリックの既知の効果。候補のカード種類から目的を推測しない。
            self.selection_purpose = {'NEW_LEAF': 'transform', 'ASTROLABE': 'transform', 'PRESERVED_FOG': 'remove',
                                      'PRECARIOUS_SHEARS': 'remove', 'PRECISE_SCISSORS': 'remove',
                                      'TRI_BOOMERANG': 'enchant', 'ELECTRIC_SHRYMP': 'enchant'}.get(entry(option.get('relic') or ''))
            if self.selection_purpose == 'enchant':
                self.selection_enchantment = {'TRI_BOOMERANG': 'INSTINCT', 'ELECTRIC_SHRYMP': 'IMBUED'}[
                    entry(option.get('relic') or '')]
            key = option.get('text_key')
            purposes = {'AROMA_OF_CHAOS.pages.INITIAL.options.LET_GO': 'transform',
                        'AROMA_OF_CHAOS.pages.INITIAL.options.MAINTAIN_CONTROL': 'upgrade',
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
                     'WOOD_CARVINGS.pages.INITIAL.options.SNAKE': 'SLITHER',
                     'SYMBIOTE.pages.INITIAL.options.APPROACH': 'CORRUPTED'}
            if key in books:
                self.selection_purpose = 'enchant'
                self.selection_enchantment = books[key]
