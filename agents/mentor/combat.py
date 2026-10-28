"""公開観測から探索用の戦闘状態を作り、実行候補へ対応させる。"""

import json

from agents.mentor.combat_history import apply_public_history

AFFLICTIONS = {name.upper(): name for name in
               ('Bound', 'Entangled', 'Galvanized', 'Hexed', 'Ringing', 'Smog', 'Weighted', 'Tainted')}


from sts2.observation import Unsupported, card_state, entry, is_boss


def resolve(raw, names, suffixes=()):
    value = entry(raw)
    for candidate in (value, value.removesuffix('_POWER'), *(value + s for s in suffixes)):
        if candidate in names:
            return candidate
    raise Unsupported(f'Mentorの語彙にない: {raw}')


def infer_enemy_moves(wire, engine):
    assumptions = []
    player_powers = {p['name']: p['amount'] for p in wire['player']['powers']}
    for enemy in wire['encounter']:
        moves = engine.monster_moves(enemy['kind'], wire['rng']['ascension'])
        if not moves:
            continue
        visible = enemy['intents'][0] if enemy['intents'] else None
        candidates = [m for m in moves if visible is not None and m['intent'] is not None
                      and m['intent']['kind'] == visible['kind']]
        if not candidates:
            candidates = [m for m in moves if m['initial']]
            method = 'initial_prior_without_matching_intent'
        else:
            method = 'public_intent_match'
        if not candidates:
            raise Unsupported(f'敵の行動遷移を構成できない: {enemy["kind"]}')
        powers = {p['name']: p['amount'] for p in enemy['powers']}

        def distance(move):
            intent = move['intent'] or {}
            damage = intent.get('amount', 0) + powers.get('STRENGTH', 0)
            multiplier = (1.5 if player_powers.get('VULNERABLE', 0) > 0 else 1) * (
                .75 if powers.get('WEAK', 0) > 0 else 1)
            amount_gap = abs(int(max(0, damage) * multiplier) - visible.get('amount', 0)) if visible and visible['kind'] == 'Attack' else 0
            hit_gap = abs(intent.get('times', 1) - visible.get('times', 1)) if visible else 0
            return hit_gap, amount_gap, 0 if wire['turn'] == 1 and move['initial'] else 1

        best = min(distance(m) for m in candidates)
        tied = sorted((m for m in candidates if distance(m) == best), key=lambda m: m['id'])
        enemy['move_state'] = tied[0]['id']
        assumptions.append({'enemy': enemy['uid'], 'kind': enemy['kind'], 'move': enemy['move_state'],
                            'alternatives': [m['id'] for m in tied], 'method': method,
                            'hit_distance': best[0], 'damage_distance': best[1]})
    wire['public_ai_assumptions'] = assumptions
    return wire


def wire_cards(items, registries):
    output = []
    for i, item in enumerate(items):
        c = card_state(item)
        facts = c['facts']
        cost = facts['energyCost']
        row = {'id': resolve(c['id'], registries['card'], ('_CARD', '_STATUS')),
               'stable_idx': i, 'kind': {'Status': 'status', 'Curse': 'curse'}.get(facts['type'], 'card'),
               'upgraded': c['upgrade'] > 0,
               'cost_override': -1 if cost['costsX'] else cost['current'],
               'flags': [k.lower() for k in c['keywords'] if k in {'Retain', 'Sly', 'Ethereal', 'Innate', 'Unplayable'}]}
        local_costs = ('local', 'afterTurn', 'afterPlay', 'afterTurnAndPlay')
        if not all(type(cost.get(k)) is int for k in local_costs):
            raise Unsupported('カードのローカル費用と失効後費用が揃っていない')
        row['public_costs'] = {key: cost[key] for key in local_costs}
        if type(cost.get('unmodified')) is not int or not isinstance(cost.get('modifiers'), list):
            raise Unsupported('カードの未修飾費用と補正列が揃っていない')
        modifiers = []
        for modifier in cost['modifiers']:
            if (modifier.get('type') not in {'Absolute', 'Relative'}
                    or type(modifier.get('amount')) is not int
                    or type(modifier.get('isReduceOnly')) is not bool
                    or type(modifier.get('expiration')) is not int
                    or modifier['expiration'] not in {0, 2, 4, 6}):
                raise Unsupported('カードの費用補正を変換できない')
            modifiers.append({'kind': modifier['type'].lower(), 'amount': modifier['amount'],
                              'reduce_only': modifier['isReduceOnly'], 'expiration': modifier['expiration']})
        row['local_cost'] = {'base': cost['unmodified'], 'costs_x': cost['costsX'], 'modifiers': modifiers}
        for keyword, flag in [('Retain', 'retain_turn'), ('Sly', 'sly_turn')]:
            if facts.get(keyword.lower()) and keyword not in c['keywords']:
                row['flags'].append(flag)
        variables = {v['name']: v['baseValue'] for v in facts['dynamicVars']}
        for source, target in [('Damage', 'base_damage'), ('Block', 'base_block')]:
            if source in variables:
                row[target] = int(variables[source])
        if c.get('special'):
            special = c['special']
            level = special.get('fakeUpgradeLevel')
            if (entry(c['id']) != 'WITHER' or type(level) is not int or level < 0
                    or special.get('baseDamage') != 3 + 3 * level
                    or variables.get('Damage') != special['baseDamage']):
                raise Unsupported(f'カードの特殊値を整合検証できない: {c["id"]}')
            row['base_damage'] = special['baseDamage']
        if c.get('enchantment'):
            effect = c['enchantment']
            row.update(enchantment=resolve(effect['id'], registries.get('enchantment', set())),
                       enchantment_amount=effect['amount'])
        if c.get('affliction'):
            effect = c['affliction']
            name = AFFLICTIONS.get(entry(effect['id']))
            if name is None:
                raise Unsupported(f'カード汚染の接続は未確認: {effect["id"]}')
            row.update(affliction=name, affliction_stacks=effect['amount'])
        output.append(row)
    return output


def wire_powers(items, registries):
    output = []
    for p in items:
        if p.get('applierCombatId') is not None or p.get('targetCombatId') is not None:
            raise Unsupported(f'付与元・対象を持つ効果の接続は未実装: {p["id"]}')
        name = resolve(p['id'], registries['power'])
        row = {'name': name, 'amount': p['amount']}
        if 'displayAmount' not in p:
            raise Unsupported(f'Power量と表示進捗が揃っていない: {p["id"]}')
        row['display'] = p['displayAmount']
        if p.get('facing') is not None:
            if name != 'SURROUNDED' or p['facing'] not in {'Right', 'Left'}:
                raise Unsupported(f'効果の公開方向を変換できない: {p["id"]}')
            row['counter'] = {'Right': 0, 'Left': 1}[p['facing']]
        if name == 'CRIMSON_MANTLE':
            variables = {v['name']: v['baseValue'] for v in p.get('dynamicVars', [])}
            if 'SelfDamage' not in variables:
                raise Unsupported('Crimson Mantleの公開SelfDamageがない')
            row['counter'] = variables['SelfDamage']
        output.append(row)
    return output


def make_wire(observation, registries, engine=None):
    if observation.get('capabilities', {}).get('observationRevision') != 'public-state-v4':
        raise Unsupported('戦闘入力には量・表示・費用期限を区別するpublic-state-v4が必要')
    status = observation['state']['status']
    combat = status['combat']
    if combat is None:
        raise Unsupported('公開戦闘状態がない')
    if combat['pets']:
        raise Unsupported('ペットの接続は未実装')

    def powers(items):
        return wire_powers(items, registries)

    encounter = []
    for enemy in combat['enemies']:
        intents = []
        for intent in enemy['intents']:
            damage, total = intent.get('damage'), intent.get('totalDamage')
            hits = max(1, int(total / damage)) if damage else 1
            intents.append({'kind': intent['type'], 'amount': damage or 0, 'times': hits})
        encounter.append({'kind': entry(enemy['modelId']), 'uid': enemy['id'], 'hp': enemy['hp'],
                          'max_hp': enemy['maxHp'], 'block': enemy['block'], 'powers': powers(enemy['powers']),
                          'intents': intents, 'intent_history': [], 'is_dead': enemy['hp'] <= 0, 'is_escaped': False})
    graph = status['map']
    node = next((n for n in graph['nodes'] if n['coord'] == graph['current']), None) if graph else None
    room = node['roomType'] if node else ''
    deck = {target: wire_cards(combat[source]['cards'], registries) for source, target in
            [('hand', 'hand'), ('draw', 'draw_pile'), ('discard', 'discard_pile'), ('exhaust', 'exhaust_pile')]}
    deck['draw_pile'].sort(key=lambda c: json.dumps({k: v for k, v in c.items() if k != 'stable_idx'}, sort_keys=True))
    for i, c in enumerate(deck['draw_pile']):
        c['stable_idx'] = i
    # Mentorの戦闘外デッキは、個体状態を持たないカードIDの多重集合。
    deck['master_deck'] = [{'id': resolve(card_state(c)['id'], registries['card'], ('_CARD', '_STATUS')),
                            'stable_idx': i, 'kind': 'card', 'upgraded': False}
                           for i, c in enumerate(status['deckCards'])]
    deck['play_pile'] = wire_cards(combat.get('play', {}).get('cards', []), registries)
    wire = {'wire_version': 1, 'game_version': 'v0.111.0', 'phase': 'PlayerPlayPhase',
            'round': combat['round'], 'turn': combat['turn'], 'side': combat['side'], 'combat_id': 0,
            'is_elite': room == 'Elite', 'intent_amounts': 'effective', 'deck': deck, 'encounter': encounter,
            'player': {'hp': status['hp'], 'max_hp': status['maxHp'], 'block': status['block'],
                       'energy': status['energy'], 'max_energy': combat['maxEnergy'],
                       'energy_regen_per_turn': status['maxEnergy'], 'stars': combat['stars'],
                       'orb_slots': combat.get('orbCapacity', 0),
                       'orbs': [{'type': resolve(entry(o['id']).removesuffix('_ORB'), registries.get('orb', set())),
                                 'passive': o['passive'], 'evoke': o['evoke']} for o in combat['orbs']],
                       'class': 'ironclad', 'gold': status['gold'], 'powers': powers(status['powers']),
                       'relics': [{'id': resolve(r['id'], registries['relic']), 'counter': r['counter'],
                                   'is_melted': r.get('isMelted', False)}
                                  for r in status['relicDetails']
                                  if entry(r['id']) not in {'DOWSING_ROD', 'NEOWS_SACRIFICE'}],
                       'potions': [resolve(s['potion']['id'], registries['potion']) if s['potion'] else None
                                   for s in status['potionBelt']['slots']]},
            'rng': {'seed': 0, 'ascension': status['ascension']}}
    apply_public_history(wire, status, wire_cards([{'state': c} for c in combat.get('drawKnownTop', [])], registries))
    return infer_enemy_moves(wire, engine) if engine is not None else wire


def match_action(action, observation):
    kind = action['action']
    enemy_slot = action.get('target_index')
    enemies = observation['state']['status']['combat']['enemies']
    target_id = enemies[enemy_slot]['id'] if enemy_slot is not None else None
    potion_slot = None
    self_potion = False
    if kind in {'potion', 'drink_potion'}:
        held = [s for s in observation['state']['status']['potionBelt']['slots'] if s['potion'] is not None]
        slot = action['slot']
        if slot < 0 or slot >= len(held):
            raise Unsupported('探索のポーション番号が所持品集合の範囲外')
        potion_slot = held[slot]['index']
        target_type = held[slot]['potion']['targetType']
        if enemy_slot is None and target_type == 'AnyEnemy':
            # 固定版MentorのDrinkPotion(None)と同じ、先頭の生存敵への解決。
            alive = next((e for e in enemies if e['hp'] > 0), None)
            target_id = alive['id'] if alive else None
        elif enemy_slot is None and target_type in {'AnyPlayer', 'Self'}:
            self_potion = True
    matches = []
    for candidate in observation['actions']:
        meta = candidate['detail']['metadata']
        if kind == 'end_turn' and candidate['kind'] == 'end_turn':
            matches.append(candidate)
        elif kind == 'play' and candidate['kind'] == 'play':
            if meta['card_index'] == action['card_index'] and meta.get('target_id') == target_id:
                matches.append(candidate)
        elif kind in {'potion', 'drink_potion'} and candidate['kind'] == 'potion':
            if meta['potion_index'] == potion_slot and (self_potion or meta.get('target_id') == target_id):
                matches.append(candidate)
    if len(matches) > 1:
        raise Unsupported('探索結果の対象が一意に対応しない')
    return matches[0] if matches else None
