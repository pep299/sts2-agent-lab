"""learnの公開観測・合法候補をSTS2の共通JSON表現へ変換する。"""

from copy import deepcopy

from sts2.observation import card_state


def normalize_observation(observation):
    obs = deepcopy(observation)
    state = obs['state']
    phase = state['phase']
    graph = state['status']['map']
    nodes = graph['nodes'] if graph else []
    for option in state.get('options') or []:
        option['relic'] = option.get('relicId')
        option['text_key'] = option['textKey']
    actions = []
    reward_rows = iter(r for r in (state.get('rewards') or {}).get('rewards', [])
                       if not r['taken'] and r['cards'] is None)
    for action in obs['actions']:
        detail = action['detail']
        native = detail['nativeKind']
        meta = {}
        if native == 'MoveTo':
            _, row, col = action['id'].split(':')
            coord = {'row': int(row), 'col': int(col)}
            node = next(n for n in nodes if n['coord'] == coord)
            meta = coord | {'room_type': node['roomType']}
        elif native == 'ChooseEventOption':
            meta = {'option_index': detail['eventOptionIndex']}
        elif native == 'PlayCard':
            meta = {'card_index': detail['handIndex'], 'target_id': detail['target']}
        elif native == 'UsePotion':
            meta = {'potion_index': detail['potionSlot'], 'target_id': detail['target']}
        elif native == 'ChooseRestOption':
            meta = {'option_key': detail['restOptionId']}
        elif native == 'TakeTreasureRelic':
            meta = {'relic_id': detail['treasureRelicId']}
        elif native == 'BuyShopItem':
            meta = {'price': detail['shopItemCost'], 'item_id': detail['shopItemId'],
                    'entry_type': {'Card': 'MerchantCardEntry', 'Relic': 'MerchantRelicEntry',
                                   'Potion': 'MerchantPotionEntry',
                                   'CardRemoval': 'MerchantCardRemovalEntry'}[detail['shopItemType']]}
        elif native == 'TakeReward':
            if detail['cardDetails']:
                c = card_state(detail)
                meta = {'card_id': c['id'], 'upgrades': c['upgrade']}
            else:
                reward = next(reward_rows)
                meta['reward_type'] = ('Potion' if reward['potionId'] is not None else
                                       'Gold' if reward['gold'] is not None else
                                       'Relic' if reward['relicId'] is not None else 'Unknown')
        elif native == 'ProceedFromRewards':
            action['kind'] = 'proceed'
        if native == 'SelectCards':
            if detail.get('parameter') != 'cardIndices':
                continue
            action['id'] = 'choose_cards:'
        action['detail'] = {'metadata': meta}
        actions.append(action)
    if phase == 'rewards' and any('card_id' in a['detail']['metadata'] for a in actions):
        for action in actions:
            if action['kind'] == 'proceed':
                action.update(kind='reward_alternative', label='Skip')
    obs['actions'] = actions
    return obs
