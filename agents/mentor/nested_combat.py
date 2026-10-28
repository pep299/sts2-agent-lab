"""直前の公開行動を再生し、公開状態が一致した子選択だけを探索する。"""

from copy import deepcopy
import json

from sts2.observation import Unsupported

PUBLIC_CARD_FIELDS = ('id', 'kind', 'upgraded', 'cost_override', 'base_damage', 'base_block',
                      'flags', 'enchantment', 'enchantment_amount', 'affliction', 'affliction_stacks')


def public_card(card, state=None):
    result = {k: card[k] for k in PUBLIC_CARD_FIELDS if k in card}
    result['flags'] = sorted(card.get('flags') or [])
    costs = card.get('public_costs')
    if costs is None and 'base_cost' in card:
        costs = {target: card.get(source, card['base_cost']) for source, target in
                 [('base_cost', 'local'), ('persistent_cost', 'afterTurn'),
                  ('played_cost', 'afterPlay'), ('stable_cost', 'afterTurnAndPlay')]}
    if costs is not None:
        result['public_costs'] = costs
    if 'local_cost' in card:
        model = card['local_cost']
        result['local_cost'] = state.local_cost_signature(card) if 'modifiers' in model and state is not None else model
    return result


def public_power(power):
    return {'name': power['name'], 'amount': power['amount'],
            'display': power.get('display', power.get('display_amount', power['amount'])),
            'counter': power.get('counter', 0)}


def public_relic(relic, counter_visible=True):
    result = {'id': relic['id'], 'is_melted': relic.get('is_melted', False)}
    if counter_visible:
        result['counter'] = relic.get('counter') or 0
    return result


def checked_snapshot(engine, wire):
    """入力にある公開意味がdecoder往復で失われないことを先に検査する。"""
    state = engine.state_from_dict(wire)
    rebuilt = engine.state_to_dict(state)
    for pile in ('hand', 'draw_pile', 'discard_pile', 'exhaust_pile', 'play_pile', 'master_deck'):
        cards = wire['deck'].get(pile, [])
        actual = rebuilt['deck'].get(pile, [])
        if len(cards) != len(actual):
            raise Unsupported(f'入力復元でカード枚数が変わった: {pile}')
        for index, (before, after) in enumerate(zip(cards, actual)):
            if 'local_cost' in before and 'local_cost' not in after:
                raise Unsupported(f'入力復元で費用補正の構造が失われた: {pile}[{index}]')
            expected, observed = public_card(before, state), public_card(after)
            for key, value in expected.items():
                if value is not None and observed.get(key) != value:
                    raise Unsupported(f'入力復元でカード属性が変わった: {pile}[{index}].{key}')
    if len(wire['encounter']) != len(rebuilt['encounter']):
        raise Unsupported('入力復元で敵の数が変わった')
    power_sets = [('player', wire['player']['powers'], rebuilt['player']['powers'])]
    power_sets += [(f'enemy[{i}]', before['powers'], after['powers']) for i, (before, after)
                   in enumerate(zip(wire['encounter'], rebuilt['encounter']))]
    for owner, expected_rows, actual_rows in power_sets:
        if len(expected_rows) != len(actual_rows):
            raise Unsupported(f'入力復元でPower数が変わった: {owner}')
        for expected, actual in zip(expected_rows, actual_rows):
            actual = public_power(actual)
            for key in ('name', 'amount', 'display', 'counter'):
                if key in expected and expected[key] != actual.get(key):
                    raise Unsupported(f'入力復元でPower状態が変わった: {owner}.{expected["name"]}.{key}')
    before_relics, after_relics = wire['player']['relics'], rebuilt['player']['relics']
    if len(before_relics) != len(after_relics):
        raise Unsupported('入力復元でレリック数が変わった')
    for expected, actual in zip(before_relics, after_relics):
        actual = public_relic(actual)
        for key in ('id', 'counter', 'is_melted'):
            if key in expected and expected[key] is not None and expected[key] != actual.get(key):
                raise Unsupported(f'入力復元でレリック状態が変わった: {expected["id"]}.{key}')
    for key in ('cards_started_this_turn', 'cards_played_this_turn', 'block_gained_card_plays_this_turn',
                'current_card_play', 'next_card_play', 'bound_card_played_this_turn',
                'pen_nib_attack_to_double', 'vambrace_triggering_card'):
        default = False if key == 'bound_card_played_this_turn' else None
        if key in wire['player'] and wire['player'][key] != rebuilt['player'].get(key, default):
            raise Unsupported(f'入力復元で公開戦闘履歴が変わった: {key}')
    for key in ('round', 'turn', 'side'):
        if key in wire and wire[key] != rebuilt.get(key):
            raise Unsupported(f'入力復元で戦闘時点が変わった: {key}')
    expected_pins, actual_pins = public_pins(wire['deck'], state), public_pins(rebuilt['deck'])
    if len(expected_pins) != len(actual_pins) or any(
            any(actual.get(key) != value for key, value in expected.items())
            for expected, actual in zip(expected_pins, actual_pins)):
        raise Unsupported('入力復元で公開山札先頭の意味・順序が変わった')
    return state, rebuilt


def public_pins(deck, state=None):
    cards = deck.get('draw_pile', [])
    pins = deck.get('pinned_top', [])
    if any(type(index) is not int or not 0 <= index < len(cards) for index in pins):
        raise Unsupported('公開山札先頭の位置が不正')
    return [public_card(cards[index], state) for index in pins]


def align_choice(engine, state, current, offered_cards):
    """公開候補の属性と実体の位置を照合し、画面と同じ候補順へ並べる。"""
    expected = [public_card(card, state) for card in offered_cards]
    choice = state.pending_choice()
    exported = engine.state_to_dict(state)
    piles = {'hand': 'hand', 'draw': 'draw_pile', 'discard': 'discard_pile',
             'exhaust': 'exhaust_pile', 'play': 'play_pile'}
    remaining = []
    random_subset = choice['kind'] == 'add_from_random_draw_subset'
    options = choice['cards']
    if random_subset:
        if len(offered_cards) != len(options):
            raise Unsupported('公開されたランダム候補の枚数が再生と一致しない')
        options = [dict(id=c['id'], upgraded=c['upgraded'], pile='draw', index=i)
                   for i, c in enumerate(exported['deck']['draw_pile'])]
    for option in options:
        if option.get('pile') not in piles or 'index' not in option:
            raise Unsupported('選択候補のカード実体の位置がない')
        card = exported['deck'][piles[option['pile']]][option['index']]
        remaining.append((option, public_card(card)))
    ordered = []
    for card in expected:
        match = next((i for i, (_, actual) in enumerate(remaining)
                      if all(actual.get(k) == value for k, value in card.items())
                      and all(card.get(k) == actual.get(k) for k in ('enchantment', 'affliction'))), None)
        if match is None:
            raise Unsupported('選択候補の属性が再生中のカード実体と一致しない')
        option, _ = remaining.pop(match)
        ordered.append(option)
    if remaining and not random_subset:
        raise Unsupported('再生中の選択に公開されていない候補がある')
    if ordered != choice['cards']:
        state.open_injected_choice(choice['kind'], ordered, choice['min_select'],
                                   choice['max_select'], choice['can_skip'], True)


def card_key(card):
    return json.dumps({k: v for k, v in card.items() if k != 'stable_idx'}, sort_keys=True)


def observed_draws(previous, current):
    """前の公開境界以後に実際に見えたドローだけを列挙する。"""
    same_turn = all(previous.get(k) == current.get(k) for k in ('round', 'turn', 'side'))
    last = max((d['sequence'] for d in previous.get('public_draws', [])), default=-1) if same_turn else -1
    return [d for d in current.get('public_draws', []) if d['sequence'] > last]


def condition_draws(engine, state, previous, current):
    """公開済みドローを説明する有限な個体対応ごとに、独立した再生状態を返す。"""
    draws = observed_draws(previous, current)
    if not draws:
        yield deepcopy(state)
        return
    piles = {'draw': 'draw_pile', 'hand': 'hand', 'discard': 'discard_pile',
             'exhaust': 'exhaust_pile', 'play': 'play_pile'}
    known = dict(previous.get('public_instances', {}))
    reserved = {(v['pile'], v['index']) for v in known.values()}
    replay = engine.state_to_dict(state)

    def matches(card, reference):
        name = reference['id'].split('.', 1)[-1]
        return (card['id'] in {name, name + '_CARD', name + '_STATUS'}
                and ('upgraded' not in reference or card['upgraded'] == reference['upgraded']))

    def assignments(index, bindings, used, options):
        if index == len(draws):
            candidate = deepcopy(state)
            try:
                candidate.condition_observed_draws(options)
            except ValueError:
                return
            yield candidate
            return
        draw = draws[index]
        reference = draw['card']
        identity = str(reference['instance'])
        locator = bindings.get(identity)
        if locator is None and identity in known:
            locator = known[identity]
            original = previous['deck'][piles[locator['pile']]][locator['index']]
            actual = replay['deck'][piles[locator['pile']]]
            position = locator['index']
            expected = public_card(original, state)
            if (position >= len(actual) or not matches(actual[position], reference)
                    or any(public_card(actual[position]).get(k) != value for k, value in expected.items()
                           if value is not None)):
                raise Unsupported('公開ドローの既知個体を再生状態へ対応できない')
        if locator is not None:
            candidates = [locator] if identity in bindings or (locator['pile'], locator['index']) not in used else []
        else:
            classes = {}
            forbidden = used | reserved
            for pile, target in piles.items():
                for position, card in enumerate(replay['deck'].get(target, [])):
                    if (pile, position) in forbidden or not matches(card, reference):
                        continue
                    position_role = ()
                    if pile == 'draw':
                        position_role = tuple((name, replay['deck'][name].index(position))
                                              for name in ('pinned_top', 'pinned_bottom')
                                              if position in replay['deck'].get(name, []))
                    signature = pile, position_role, json.dumps(public_card(card), sort_keys=True)
                    classes.setdefault(signature, {'pile': pile, 'index': position})
            candidates = classes.values()
        for locator in candidates:
            card = replay['deck'][piles[locator['pile']]][locator['index']]
            if not matches(card, reference):
                continue
            yield from assignments(index + 1, {**bindings, identity: locator},
                                   used | {(locator['pile'], locator['index'])},
                                   options + [dict(locator, id=card['id'], upgraded=card['upgraded'])])

    yield from assignments(0, {}, set(), [])


def apply_public_action(state, action):
    if action['action'] == 'start_relic_choice':
        state.open_relic_start_choice(action['relic'])
    elif action['action'] == 'choose':
        state.resolve_public_choice(action['selection'])
    else:
        state.apply(action)


def public_projection(wire, observed=None):
    def fields(row, keys):
        return {k: row[k] for k in keys if k in row}
    def powers(rows):
        return [public_power(p) for p in rows]
    player = fields(wire['player'], ('hp', 'max_hp', 'block', 'energy', 'max_energy',
                    'energy_regen_per_turn', 'gold', 'stars', 'class', 'potions', 'orbs', 'orb_slots',
                    'cards_started_this_turn', 'cards_played_this_turn', 'bound_card_played_this_turn',
                    'pen_nib_attack_to_double', 'vambrace_triggering_card'))
    player['powers'] = powers(wire['player']['powers'])
    visible = {r['id'] for r in (observed or wire)['player']['relics'] if r.get('counter') is not None}
    player['relics'] = [public_relic(r, r['id'] in visible) for r in wire['player']['relics']]
    block_plays = wire['player'].get('block_gained_card_plays_this_turn', [])
    current = wire['player'].get('current_card_play')
    other = {}
    player['block_gained_card_plays_this_turn'] = [
        'current' if tag == current else other.setdefault(tag, len(other)) for tag in block_plays]
    player['current_card_play'] = current is not None
    for relic in player['relics']:
        if relic['id'] == 'VAMBRACE' and relic.get('counter', 0) is not None and relic['counter'] < 0:
            locator = next(({'pile': pile, 'index': index}
                            for pile, target in [('draw', 'draw_pile'), ('hand', 'hand'), ('discard', 'discard_pile'),
                                                 ('exhaust', 'exhaust_pile'), ('play', 'play_pile')]
                            for index, card in enumerate(wire['deck'].get(target, []))
                            if card.get('stable_idx') == -relic['counter']), None)
            if locator is None:
                raise Unsupported('Vambraceの発動元を公開カード位置へ正規化できない')
            relic['counter'] = {'triggering_card': locator}
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
    result = {'player': player, 'deck': deck, 'encounter': enemies, 'round': wire['round'], 'turn': wire['turn'],
              'side': wire.get('side', 'Player')}
    result['deck']['draw_pile'].sort(key=lambda c: json.dumps(c, sort_keys=True))
    result['deck']['pinned_top'] = public_pins(wire['deck'])
    return result


def align_public_boundary(engine, state, current, cards, minimum=None, maximum=None, can_skip=None):
    pending = state.pending_choice()
    if pending is None:
        raise Unsupported('直前の行動を再生しても子選択が開かない')
    low = pending['min_select'] if minimum is None else minimum
    high = pending['max_select'] if maximum is None else maximum
    curse_subset = (pending['kind'] == 'monster_curse_select' and (low, high) == (0, 1)
                    and pending['min_select'] == pending['max_select'] == 1)
    if (low, high) != (pending['min_select'], pending['max_select']) and not curse_subset:
        raise Unsupported('子選択の公開枚数が再生と一致しない')
    if can_skip is not None and can_skip != pending['can_skip']:
        raise Unsupported('子選択の公開skip可否が再生と一致しない')
    if cards is not None:
        if not cards or isinstance(cards[0], dict):
            candidate_input = deepcopy(current)
            hand = candidate_input['deck']['hand']
            count = len(hand)
            hand.extend(cards)
            _, candidate_output = checked_snapshot(engine, candidate_input)
            cards = candidate_output['deck']['hand'][count:]
            if engine.choice_kind_is_generative(pending['kind']):
                state.open_generated_choice(pending['kind'], cards, pending['min_select'],
                                            pending['max_select'], pending['can_skip'])
            else:
                align_choice(engine, state, current, cards)
        else:
            actual = [(c['id'], c['upgraded']) for c in pending['cards']]
            if actual != list(map(tuple, cards)):
                raise Unsupported('子選択の公開候補が再生と一致しない')


def resume_choice(engine, previous, action, current, offered=None, history=(), *,
                  minimum=None, maximum=None, can_skip=None):
    wire = deepcopy(previous)
    first_current = history[0]['current'] if history else current
    first_offered = history[0]['cards'] if history else offered
    if first_offered and isinstance(first_offered[0], dict):
        first_offered = [(c['id'], c['upgraded']) for c in first_offered]
    stages = {('DISINTEGRATION', 'MIND_ROT'): 0, ('DISINTEGRATION', 'SLOTH_STATUS'): 1,
              ('DISINTEGRATION', 'WASTE_AWAY'): 2}
    stage = stages.get(tuple(name for name, upgraded in first_offered or []))
    if action['action'] == 'end_turn' and stage is not None and len(wire['encounter']) == 1:
        boss = wire['encounter'][0]
        if boss['kind'] == 'KNOWLEDGE_DEMON' and any(i['kind'] == 'Debuff' for i in boss['intents']):
            # 公開された呪い候補から、既に実行された敵の行動と段階を特定する。
            boss.update(move_state='CURSE_OF_KNOWLEDGE', curse_of_knowledge_counter=stage)
    if action['action'] == 'play' and 'public_draws' not in first_current:
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
    boundaries = [dict(step) for step in history] + [
        {'current': current, 'cards': offered, 'minimum': minimum, 'maximum': maximum, 'can_skip': can_skip}]
    for boundary in boundaries:
        _, normalized = checked_snapshot(engine, boundary['current'])
        boundary['projection'] = public_projection(normalized, boundary['current'])
    attempts = 0
    failure = '直前の行動を再生しても子選択が開かない'

    def replay(source):
        state, _ = checked_snapshot(engine, source)
        def advance(base, before, operation, index):
            nonlocal attempts, failure
            boundary = boundaries[index]
            try:
                for candidate in condition_draws(engine, base, before, boundary['current']):
                    attempts += 1
                    try:
                        apply_public_action(candidate, operation)
                        if not candidate.observed_draws_consumed():
                            failure = '公開済みドローを再生元のカード集合から合法に再生できない'
                            continue
                        actual = public_projection(engine.state_to_dict(candidate), boundary['current'])
                        different = [key for key, value in boundary['projection'].items() if value != actual[key]]
                        if different:
                            failure = f'子選択の再生と公開状態が一致しない: {different[0]}'
                            continue
                        align_public_boundary(engine, candidate, boundary['current'], boundary.get('cards'),
                                              boundary.get('minimum'), boundary.get('maximum'), boundary.get('can_skip'))
                    except (Unsupported, ValueError) as exc:
                        failure = str(exc)
                        continue
                    if index == len(history):
                        yield candidate
                    else:
                        yield from advance(candidate, boundary['current'],
                                           {'action': 'choose', 'selection': history[index]['indices']}, index + 1)
            except Unsupported as exc:
                failure = str(exc)
        return next(advance(state, source, action, 0), None)

    state = replay(wire)
    if state is not None:
        return state, {'method': 'public_action_replay', 'attempts': attempts, 'earlier_choices': len(history)}
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
            return replayed, {'method': 'observed_random_outcome', 'attempts': attempts,
                              'hypothesis_seed': seed, 'actual_rng_recovered': False,
                              'earlier_choices': len(history)}
        raise Unsupported('Catastrophe内Wishの公開状態・候補に一致する再生仮説が4096試行で見つからない')
    if attempts == 0:
        raise Unsupported('公開済みドローを再生元のカード集合へ対応できない')
    raise Unsupported(failure)


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
