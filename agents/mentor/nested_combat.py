"""直前の公開行動を再生し、公開状態が一致した子選択だけを探索する。"""

from copy import deepcopy
import json

from sts2.observation import Unsupported

PUBLIC_CARD_FIELDS = ('id', 'kind', 'upgraded', 'base_cost', 'cost_override', 'base_damage', 'base_block',
                      'flags', 'enchantment', 'enchantment_amount', 'affliction', 'affliction_stacks')


def public_card(card):
    return {k: card[k] for k in PUBLIC_CARD_FIELDS if k in card}


def align_choice(engine, state, current, offered_cards):
    """公開候補の属性と実体の位置を照合し、画面と同じ候補順へ並べる。"""
    normalization = deepcopy(current)
    normalization['deck']['hand'] = offered_cards
    expected = engine.state_to_dict(engine.state_from_dict(normalization))['deck']['hand']
    choice = state.pending_choice()
    exported = engine.state_to_dict(state)
    piles = {'hand': 'hand', 'draw': 'draw_pile', 'discard': 'discard_pile',
             'exhaust': 'exhaust_pile', 'play': 'play_pile'}
    remaining = []
    for option in choice['cards']:
        if option.get('pile') not in piles or 'index' not in option:
            raise Unsupported('選択候補のカード実体の位置がない')
        card = exported['deck'][piles[option['pile']]][option['index']]
        remaining.append((option, public_card(card)))
    ordered = []
    for card in expected:
        match = next((i for i, (_, actual) in enumerate(remaining) if actual == public_card(card)), None)
        if match is None:
            raise Unsupported('選択候補の属性が再生中のカード実体と一致しない')
        option, _ = remaining.pop(match)
        ordered.append(option)
    if remaining:
        raise Unsupported('再生中の選択に公開されていない候補がある')
    if ordered != choice['cards']:
        state.open_injected_choice(choice['kind'], ordered, choice['min_select'],
                                   choice['max_select'], choice['can_skip'], True)


def card_key(card):
    return json.dumps({k: v for k, v in card.items() if k != 'stable_idx'}, sort_keys=True)


def public_projection(wire):
    def fields(row, keys):
        return {k: row[k] for k in keys if k in row}
    def powers(rows):
        return [fields(p, ('name', 'amount')) for p in rows]
    player = fields(wire['player'], ('hp', 'max_hp', 'block', 'energy', 'max_energy',
                    'energy_regen_per_turn', 'gold', 'stars', 'class', 'potions', 'orbs', 'orb_slots'))
    player['powers'] = powers(wire['player']['powers'])
    player['relics'] = [fields(r, ('id', 'counter')) for r in wire['player']['relics']]
    deck = {pile: [public_card(c) for c in wire['deck'].get(pile, [])]
            for pile in ('hand', 'draw_pile', 'discard_pile', 'exhaust_pile', 'play_pile', 'master_deck')}
    enemies = []
    for enemy in wire['encounter']:
        if enemy.get('is_dead') or enemy['hp'] <= 0 or enemy.get('is_escaped'):
            continue
        row = fields(enemy, ('kind', 'hp', 'max_hp', 'block', 'is_dead', 'is_escaped'))
        row['powers'] = powers(enemy['powers'])
        row['intents'] = [fields(i, ('kind', 'amount', 'times', 'effective_amount')) for i in enemy['intents']]
        enemies.append(row)
    result = {'player': player, 'deck': deck, 'encounter': enemies, 'round': wire['round'], 'turn': wire['turn']}
    result['deck']['draw_pile'].sort(key=lambda c: json.dumps(c, sort_keys=True))
    return result


def resume_choice(engine, previous, action, current, offered=None, history=()):
    wire = deepcopy(previous)
    first_current = history[0]['current'] if history else current
    first_offered = [(c['id'], c['upgraded']) for c in history[0]['cards']] if history else offered
    stages = {('DISINTEGRATION', 'MIND_ROT'): 0, ('DISINTEGRATION', 'SLOTH_STATUS'): 1,
              ('DISINTEGRATION', 'WASTE_AWAY'): 2}
    stage = stages.get(tuple(name for name, upgraded in first_offered or []))
    if action['action'] == 'end_turn' and stage is not None and len(wire['encounter']) == 1:
        boss = wire['encounter'][0]
        if boss['kind'] == 'KNOWLEDGE_DEMON' and any(i['kind'] == 'Debuff' for i in boss['intents']):
            # 公開された呪い候補から、既に実行された敵の行動と段階を特定する。
            boss.update(move_state='CURSE_OF_KNOWLEDGE', curse_of_knowledge_counter=stage)
    if action['action'] == 'play':
        played = wire['deck']['hand'][action['card_index']]
        if played['id'] == 'PREPARED':
            kept = [c for i, c in enumerate(wire['deck']['hand']) if i != action['card_index']]
            hand = first_current['deck']['hand']
            if [card_key(c) for c in kept] != [card_key(c) for c in hand[:len(kept)]]:
                raise Unsupported('Prepared後の既存手札が再生元と一致しない')
            drawn = []
            for visible in hand[len(kept):]:
                match = next((i for i, c in enumerate(wire['deck']['draw_pile']) if card_key(c) == card_key(visible)), None)
                if match is None:
                    raise Unsupported('Preparedの公開済みドローを山札集合から再生できない')
                drawn.append(wire['deck']['draw_pile'].pop(match))
            # 既に見えたドロー結果だけを再生する。次の判断の探索ではbeliefdrawを使う。
            wire['deck']['draw_pile'] = drawn + wire['deck']['draw_pile']
    observed = public_projection(engine.state_to_dict(engine.state_from_dict(current)))
    def replay(source):
        state = engine.state_from_dict(source)
        state.apply(action)
        for step in history:
            if state.pending_choice() is None:
                return None
            expected = public_projection(engine.state_to_dict(engine.state_from_dict(step['current'])))
            if public_projection(engine.state_to_dict(state)) != expected:
                return None
            try:
                align_choice(engine, state, step['current'], step['cards'])
            except Unsupported:
                return None
            state.apply({'action': 'choose', 'selection': step['indices']})
        return state

    state = replay(wire)
    if state is None and history:
        pending, different = None, ['earlier_choice']
    else:
        pending = state.pending_choice()
        predicted = public_projection(engine.state_to_dict(state))
        different = [key for key in observed if observed[key] != predicted[key]]
    if pending is not None and not different:
        return state, {'method': 'public_action_replay', 'attempts': 1, 'earlier_choices': len(history)}
    # Catastropheの抽選は非公開。既に公開された結果に合う乱数の仮説を探す。
    # 元の乱数の復元とは扱わず、未来の状態・実ゲームのseedは参照しない。
    played = wire['deck']['hand'][action['card_index']] if action['action'] == 'play' else None
    stack = current['deck'].get('play_pile', [])
    if played and played['id'] == 'CATASTROPHE' and stack and stack[-1]['id'] == 'WISH':
        for seed in range(4096):
            candidate = deepcopy(wire)
            candidate['rng'] = dict(candidate['rng'], run_seed=seed)
            candidate['rng'].pop('counters', None)
            replayed = replay(candidate)
            if replayed is None:
                continue
            choice = replayed.pending_choice()
            if choice is None or choice['kind'] != 'add_from_draw_to_hand':
                continue
            options = [(c['id'], c['upgraded']) for c in choice['cards']]
            if offered is not None and options != list(map(tuple, offered)):
                continue
            if public_projection(engine.state_to_dict(replayed)) == observed:
                return replayed, {'method': 'observed_random_outcome', 'attempts': seed + 1,
                                  'hypothesis_seed': seed, 'actual_rng_recovered': False,
                                  'earlier_choices': len(history)}
        raise Unsupported('Catastrophe内Wishの公開状態・候補に一致する再生仮説が4096試行で見つからない')
    if pending is None:
        raise Unsupported('直前の行動を再生しても子選択が開かない')
    raise Unsupported(f'子選択の再生と公開状態が一致しない: {different[0]}')


def search_indices(engine, state, minimum, maximum, count, *, sims, threads):
    indices = []
    searches = []
    for _ in range(maximum + 1):
        result = engine.mcts_recommend(state, sims=sims, threads=threads, hidden_info='beliefdraw', seed=0)
        choice = result['actions'][0]['action']
        picked = choice.get('selection', [choice['index']] if 'index' in choice else None)
        if choice['action'] != 'choose' or picked is None:
            raise Unsupported('MCTS子選択がカード番号を返さない')
        if len(set(picked)) != len(picked) or any(i < 0 or i >= count or i in indices for i in picked):
            raise Unsupported('MCTS子選択に重複・候補外の番号がある')
        indices.extend(picked)
        searches.append(choice)
        if not picked or len(indices) >= maximum:
            break
        state.apply(choice)
        if state.pending_choice() is None:
            break
    if not minimum <= len(indices) <= maximum:
        raise Unsupported('MCTS子選択の枚数が公開された制約に合わない')
    return indices, searches
