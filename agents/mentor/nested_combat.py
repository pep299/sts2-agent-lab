"""直前の公開行動を再生し、公開状態が一致した子選択だけを探索する。"""

from copy import deepcopy
import json

from combat import Unsupported


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
    card_fields = ('id', 'kind', 'upgraded', 'base_cost', 'cost_override', 'base_damage', 'base_block',
                   'flags', 'enchantment', 'enchantment_amount', 'affliction', 'affliction_stacks')
    deck = {pile: [fields(c, card_fields) for c in wire['deck'].get(pile, [])]
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


def resume_choice(engine, previous, action, current, offered=None):
    wire = deepcopy(previous)
    stages = {('DISINTEGRATION', 'MIND_ROT'): 0, ('DISINTEGRATION', 'SLOTH_STATUS'): 1,
              ('DISINTEGRATION', 'WASTE_AWAY'): 2}
    stage = stages.get(tuple(name for name, upgraded in offered or []))
    if action['action'] == 'end_turn' and stage is not None and len(wire['encounter']) == 1:
        boss = wire['encounter'][0]
        if boss['kind'] == 'KNOWLEDGE_DEMON' and any(i['kind'] == 'Debuff' for i in boss['intents']):
            # 公開された呪い候補から、既に実行された敵の行動と段階を特定する。
            boss.update(move_state='CURSE_OF_KNOWLEDGE', curse_of_knowledge_counter=stage)
    if action['action'] == 'play':
        played = wire['deck']['hand'][action['card_index']]
        if played['id'] == 'PREPARED':
            kept = [c for i, c in enumerate(wire['deck']['hand']) if i != action['card_index']]
            hand = current['deck']['hand']
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
    state = engine.state_from_dict(wire)
    state.apply(action)
    pending = state.pending_choice()
    if pending is None:
        raise Unsupported('直前の行動を再生しても子選択が開かない')
    observed = public_projection(engine.state_to_dict(engine.state_from_dict(current)))
    predicted = public_projection(engine.state_to_dict(state))
    for key in observed:
        if observed[key] != predicted[key]:
            raise Unsupported(f'子選択の再生と公開状態が一致しない: {key}')
    return state


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
