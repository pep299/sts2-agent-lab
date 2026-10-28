"""公開されたカード個体・プレイ・既発生効果をMentorの参照へ対応させる。"""

from sts2.observation import Unsupported, card_state, entry


PILES = (('draw', 'draw_pile'), ('hand', 'hand'), ('discard', 'discard_pile'),
         ('exhaust', 'exhaust_pile'), ('play', 'play_pile'))
CARD_TYPES = ('Attack', 'Skill', 'Power', 'Curse', 'Status')


def apply_public_history(wire, status, known_top=()):
    combat = status['combat']
    history = combat.get('history')
    if history is None or history['coverage'] != 'current_turn':
        raise Unsupported('現在のside-turnの公開戦闘履歴が必要')
    owner = combat['ownerId']
    player = wire['player']
    locations = {}
    visible_cards = {}
    remaining = list(wire['deck']['draw_pile'])
    pinned = []
    for card in known_top:
        signature = {k: v for k, v in card.items() if k != 'stable_idx'}
        index = next((i for i, c in enumerate(remaining)
                      if {k: v for k, v in c.items() if k != 'stable_idx'} == signature), None)
        if index is None:
            raise Unsupported('公開された山札先頭のカードが山札集合にない')
        pinned.append(remaining.pop(index))
    wire['deck']['draw_pile'] = pinned + remaining
    wire['deck']['pinned_top'] = list(range(len(pinned)))
    for index, card in enumerate(wire['deck']['draw_pile']):
        card['stable_idx'] = index
    for index, raw in enumerate(combat.get('drawKnownTop', [])):
        instance = raw.get('instance')
        if instance is None or instance in locations:
            raise Unsupported('公開された山札先頭のカード個体が不正')
        locations[instance] = {'pile': 'draw', 'index': index}
        visible_cards[instance] = pinned[index]
    for pile, target in PILES:
        if pile == 'draw':
            continue
        raw = [card_state(c) for c in combat.get(pile, {}).get('cards', [])]
        for index, c in enumerate(raw):
            instance = c.get('instance')
            if instance is None:
                continue
            if instance in locations:
                raise Unsupported('公開カード個体が複数のpileに存在する')
            locations[instance] = {'pile': pile, 'index': index}
            visible_cards[instance] = wire['deck'][target][index]

    def locator(reference):
        if reference is None:
            return None
        instance = reference.get('instance')
        found = locations.get(instance)
        if found is None:
            raise Unsupported('公開発動元のカード個体を現在のpileへ対応できない')
        raw_id = entry(reference['id'])
        if visible_cards[instance]['id'] not in {raw_id, raw_id + '_CARD', raw_id + '_STATUS'}:
            raise Unsupported('発動元の個体とカードIDが一致しない')
        return dict(found)

    def count_types(plays):
        buckets = [0] * len(CARD_TYPES)
        for play in plays:
            try:
                buckets[CARD_TYPES.index(play['card']['type'])] += 1
            except ValueError as exc:
                raise Unsupported('公開プレイのカード種別を変換できない') from exc
        return buckets

    started = [p for p in history['playsStarted'] if p['ownerId'] == owner]
    finished = [p for p in history['playsFinished'] if p['ownerId'] == owner]
    ids = [p['playId'] for p in started]
    if len(set(ids)) != len(ids) or any(type(p) is not int or not 0 < p < 2**32 - 1 for p in ids):
        raise Unsupported('公開CardPlayの識別子が不正')
    done = {p['playId'] for p in finished}
    if not done <= set(ids):
        raise Unsupported('完了プレイに対応する開始履歴がない')
    active = [p for p in ids if p not in done]
    player['cards_started_this_turn'] = count_types(started)
    player['cards_played_this_turn'] = count_types(finished)
    player['current_card_play'] = active[-1] if active else None
    player['block_gained_card_plays_this_turn'] = [
        block['cardPlay']['playId'] for block in history['blockGained']
        if block['receiverId'] == owner and block['cardPlay'] is not None
        and block['cardPlay']['ownerId'] == owner]
    tags = ids + player['block_gained_card_plays_this_turn']
    if any(type(tag) is not int or not 0 < tag < 2**32 - 1 for tag in tags):
        raise Unsupported('Block獲得元の公開CardPlay識別子が不正')
    player['next_card_play'] = max(tags, default=0) + 1
    bound = combat.get('boundCardPlayedThisTurn')
    if type(bound) is not bool:
        raise Unsupported('Boundの公開使用状態がない')
    player['bound_card_played_this_turn'] = bound
    for power in player['powers']:
        if power['name'] == 'JUGGLING':
            power['counter'] = player['cards_started_this_turn'][0]
    details = {entry(r['id']): r for r in status['relicDetails']}
    for relic in player['relics']:
        name = relic['id']
        if relic['is_melted'] or name not in {'PEN_NIB', 'CENTENNIAL_PUZZLE', 'VAMBRACE'}:
            continue
        effect = details[name].get('effectState')
        if effect is None:
            raise Unsupported(f'レリックの公開消費状態がない: {name}')
        if name == 'PEN_NIB':
            relic['counter'] = effect['attacksPlayed'] % 10
            player['pen_nib_attack_to_double'] = locator(effect['attackToDouble'])
        elif name == 'CENTENNIAL_PUZZLE':
            relic['counter'] = int(effect['usedThisCombat'])
        else:
            relic['counter'] = int(effect['blockGainedThisCombat'])
            player['vambrace_triggering_card'] = None if relic['counter'] else locator(effect['triggeringCard'])
    wire['public_draws'] = history['draws']
    wire['public_instances'] = {str(k): dict(v) for k, v in locations.items()}
    return wire
