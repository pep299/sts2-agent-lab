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
        elif native == 'ChooseBundle':
            action['kind'] = 'choose_bundle'
            meta = {'bundle_index': detail['bundleIndex']}
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
        elif native in ('OpenShop', 'CloseShop', 'LeaveShop'):
            action['kind'] = {'OpenShop': 'shop_open', 'CloseShop': 'shop_close',
                              'LeaveShop': 'shop_leave'}[native]
        elif native == 'ClickCrystalSphereCell':
            action['kind'] = 'crystal_sphere_click'
            meta = {'col': detail['crystalSphereCol'], 'row': detail['crystalSphereRow']}
        elif native == 'SetCrystalSphereTool':
            action['kind'] = 'crystal_sphere_tool'
            meta = {'tool': detail['crystalSphereTool']}
        elif native == 'TakeReward':
            if detail['cardDetails']:
                c = card_state(detail)
                meta = {'card_id': c['id'], 'upgrades': c['upgrade']}
            else:
                meta['reward_type'] = {'PotionReward': 'Potion', 'GoldReward': 'Gold',
                                       'RelicReward': 'Relic'}[detail['rewardType']]
                if detail['relicId'] is not None:
                    meta['relic_id'] = detail['relicId']
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
