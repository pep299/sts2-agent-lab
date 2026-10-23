"""公開観測と合法候補からMCTS・配布PPOで選ぶMentor方策。"""

import argparse
import hashlib
import importlib.util
from importlib.machinery import ExtensionFileLoader
import json
import math
from pathlib import Path
import sys
import time
import tomllib
import traceback

from combat import Unsupported, card_state, is_boss, make_wire, match_action, resolve
from selection_context import SelectionContext
from nested_combat import resume_choice, search_indices

REPO = Path(__file__).resolve().parents[2]


def default_config():
    local = REPO / 'config/mentor.local.toml'
    return local if local.is_file() else REPO / 'config/mentor.example.toml'


def asset_path(value):
    path = Path(value).expanduser()
    return path if path.is_absolute() else REPO / path


def metadata(action):
    return action['detail']['metadata']


def strategic_actions(observation):
    combat = observation['state']['phase'] == 'combat'
    return [a for a in observation['actions'] if a['kind'] != 'discard_potion'
            and (combat or a['kind'] != 'potion')]


def reward_claims(observation, actions, declined=()):
    full = all(s['potion'] is not None for s in observation['state']['status']['potionBelt']['slots'])
    return [a for a in actions if a['kind'] == 'reward' and a['id'] not in declined and
            not (full and metadata(a).get('reward_type') == 'Potion')]


def card(item):
    c = card_state(item)
    return {'id': c['id'], 'upgrade_level': c['upgrade'], 'keywords': c['keywords'],
            'enchantment': c.get('enchantment')}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class Mentor:
    def __init__(self, configuration, context=None):
        config = tomllib.loads(Path(configuration).read_text())
        library = asset_path(config['paths']['extension'])
        model = asset_path(config['paths']['model'])
        if sha(model) != config['identity']['model_sha256']:
            raise ValueError('Mentor model hash differs from configuration')
        spec = importlib.util.spec_from_file_location('sts2_rs', library,
                    loader=ExtensionFileLoader('sts2_rs', str(library)))
        self.engine = importlib.util.module_from_spec(spec)
        sys.modules['sts2_rs'] = self.engine
        spec.loader.exec_module(self.engine)
        if self.engine.build_git() != config['identity']['build_git']:
            raise ValueError('Mentor extension build differs from configuration')
        self.net = self.engine.PpoNetPolicy(str(model), config['identity']['features'])
        self.search = config['search']
        if any(type(self.search.get(k)) is not int or self.search[k] < 1
               for k in ('sims', 'boss_sims', 'threads')):
            raise ValueError('searchのsims・boss_sims・threadsは正の整数を指定')
        self.registries = {kind: set(self.engine.list_registry_names(kind))
                           for kind in ['card', 'power', 'relic', 'potion', 'enchantment', 'orb']}
        self.declined_card_rewards = set()
        self.card_reward_parent = None
        self.reward_room = None
        self.context = context or SelectionContext()
        self.previous_combat = None
        self.last_signature = None
        self.repeated_decisions = 0
        self.selection_fallback = False

    @staticmethod
    def room_key(observation):
        status = observation['state']['status']
        return status['act'], status['floor']

    def common(self, observation):
        s = observation['state']['status']
        graph = s['map']
        if graph is None:
            raise Unsupported('公開マップがない')
        return {'floor': s['floor'], 'act': s['act'], 'run_state': {
            'hp': s['hp'], 'max_hp': s['maxHp'], 'gold': s['gold'], 'ascension': s['ascension'],
            'master_deck': [card(c) for c in s['deckCards']], 'relics': [{'id': r} for r in s['relics']],
            'potions': [{'id': x['potion']['id'], 'empty': False} if x['potion'] else {'empty': True}
                        for x in s['potionBelt']['slots']]},
            'map': {'nodes': [dict(n['coord'], type=n['roomType'], children=n['children']) for n in graph['nodes']],
                    'current': graph['current'],
                    'boss': dict(graph['boss'], id=graph['bossId']) if graph['boss'] else None}}

    def score(self, packet, responses):
        probs, value = self.net.distribution(packet['obs'], packet['actions'], {})
        if len(probs) != len(responses) or not math.isfinite(value) or any(not math.isfinite(p) or p < 0 for p in probs) or abs(sum(probs)-1) > 1e-4:
            raise Unsupported('PPOの確率・候補対応が不正')
        best = max(range(len(probs)), key=probs.__getitem__)
        return responses[best], {'source': 'ppo', 'actions': packet['actions'],
                                 'probs': probs, 'value': value, 'chosen': best}

    def selection(self, observation, base):
        state = observation['state']
        selection = state['selection']
        if state['status']['combat'] is not None:
            raise Unsupported('戦闘中の子選択を探索状態へ対応させる接続は未実装')
        if selection is None or selection['min'] < 1:
            raise Unsupported('任意枚数の選択は未実装')
        cards = selection['cards']
        # 共通観測の生成だけを既存Rustビルダーに任せる。
        packet = self.engine.ppo_wire_obs(base | {'type': 'card_reward', 'cards': [], 'can_skip': True}, 'card_reward')
        obs = packet['obs']
        obs.pop('card_reward_option_ids', None)
        obs.pop('card_reward_option_upgraded', None)
        obs['phase'] = 'card_select'
        pairs = [(card(c)['id'], bool(card(c)['upgrade_level'])) for c in cards]
        purpose = selection['purpose'].lower()
        if 'transform' in purpose or 'enchant' in purpose:
            name = 'transform' if 'transform' in purpose else 'enchant'
            deck = [(c['id'], bool(c['upgrade_level'])) for c in base['run_state']['master_deck']]
            obs[f'{name}_select_deck_indices'] = [deck.index(pair) for pair in pairs]
            if name == 'enchant':
                obs['pending_enchantment'] = selection.get('enchantment') or self.context.selection_enchantment
            kind = f'{name}_deck_card'
        elif 'remov' in purpose:
            obs['card_removal_options'] = pairs
            kind = 'remove_deck_card'
        elif 'upgrad' in purpose:
            obs['smith_options'] = [pair[0] for pair in pairs]
            kind = 'smith_card'
        elif 'obtain' in purpose or 'add' in purpose or 'grant' in purpose:
            obs['card_grant_options'] = pairs
            kind = 'grant_deck_card'
        else:
            raise Unsupported(f'選択目的が未対応: {selection["purpose"]}')
        packet['actions'] = [{'action': kind, 'idx': i} for i in range(len(cards))]
        probs, value = self.net.distribution(obs, packet['actions'], {})
        count = selection['min']
        indices = sorted(sorted(range(len(cards)), key=lambda i: (-probs[i], i))[:count])
        return {'action_id': 'choose_cards:', 'indices': indices}, {
            'source': 'ppo_selection', 'purpose': selection['purpose'], 'probs': probs, 'value': value,
            'multi_pick': 'single inference top-k' if count > 1 else None}

    def noncombat(self, observation):
        state = observation['state']
        base = self.common(observation)
        actions = strategic_actions(observation)
        if state['phase'] == 'grid_selection':
            return self.selection(observation, base)
        surface = None
        if state['phase'] == 'map':
            surface = 'map_select'
            base['nodes'] = [dict(metadata(a), index=i, type=metadata(a)['room_type']) for i, a in enumerate(actions)]
        elif state['phase'] == 'event':
            surface = 'event'
            options = {o['index']: o for o in state['options']}
            base['options'] = []
            for i, a in enumerate(actions):
                o = options[metadata(a)['option_index']]
                row = dict(o, index=i, label=o['relic'] or o['title'], event_id=state['eventId'])
                if o['relic']:
                    row['relic'] = {'id': o['relic']}
                base['options'].append(row)
        elif state['phase'] == 'rest':
            surface = 'rest_site'
            labels = [metadata(a)['option_key'] for a in actions]
            if labels != ['HEAL', 'SMITH'] and self.selection_fallback:
                actions = [a for a in actions if metadata(a)['option_key'] in {'HEAL', 'SMITH'}]
                labels = [metadata(a)['option_key'] for a in actions]
            if labels != ['HEAL', 'SMITH']:
                raise Unsupported(f'配布休憩ビルダーとの対応が未確認: {labels}')
            base['options'] = [dict(index=i, id=label, enabled=True) for i, label in enumerate(labels)]
        elif state['phase'] == 'shop':
            destinations = [a for a in actions if a['kind'] == 'map']
            if destinations:
                buys = [a for a in actions if a['kind'] == 'buy']
                shop = dict(observation, actions=buys + [{'id': 'mentor:leave_shop', 'kind': 'shop_leave', 'detail': {'metadata': {}}}])
                response, info = self.noncombat(shop)
                if response['action_id'] != 'mentor:leave_shop':
                    return response, info
                move = dict(observation, state=dict(state, phase='map'), actions=destinations)
                response, map_info = self.noncombat(move)
                return response, {'source': 'ppo_shop_then_map', 'shop': info, 'map': map_info}
            surface = 'shop'
            base['options'] = []
            for i, a in enumerate(actions):
                m = metadata(a)
                if a['kind'] == 'shop_leave':
                    option = {'action': 'leave_shop'}
                elif a['kind'] == 'buy':
                    kind = {'MerchantCardEntry': 'buy_card', 'MerchantRelicEntry': 'buy_relic',
                            'MerchantPotionEntry': 'buy_potion', 'MerchantCardRemovalEntry': 'remove_card'}[m['entry_type']]
                    option = {'action': kind, 'price': m['price'], 'item': {'id': m.get('item_id')}}
                else:
                    raise Unsupported(f'店候補が未対応: {a["kind"]}')
                base['options'].append(option | {'index': i, 'enabled': True})
        elif state['phase'] == 'treasure':
            take = [a for a in actions if a['kind'] == 'claim_relic']
            skip = [a for a in actions if a['kind'] == 'skip_treasure']
            if len(take) != 1 or len(skip) != 1:
                raise Unsupported('複数レリックの宝箱は未対応')
            packet = self.engine.ppo_wire_obs(base | {'type': 'card_reward', 'cards': [], 'can_skip': True}, 'card_reward')
            packet['obs']['phase'] = 'relic_reward'
            packet['obs']['relic_reward_ids'] = [metadata(take[0])['relic_id']]
            packet['actions'] = [{'action': 'pick_relic_reward'}, {'action': 'skip_relic'}]
            return self.score(packet, [{'action_id': take[0]['id']}, {'action_id': skip[0]['id']}])
        elif state['phase'] == 'rewards':
            claims = reward_claims(observation, actions, self.declined_card_rewards)
            collections = [a for a in claims if a['detail']['nativeKind'] == 'CollectReward']
            if collections:
                return {'action_id': collections[0]['id']}, {'source': 'fixed_reward_collection'}
            cards = [a for a in actions if a['detail']['nativeKind'] == 'TakeReward']
            if cards:
                surface = 'card_reward'
                alternatives = [a for a in actions if a['kind'] == 'reward_alternative']
                if any(a['label'].strip().lower() != 'skip' for a in alternatives):
                    raise Unsupported('カード報酬の代替効果が未対応')
                actions = cards + alternatives
                base['cards'] = [{'id': metadata(a)['card_id'], 'upgrade_level': metadata(a)['upgrades']} for a in cards]
                base['can_skip'] = bool(alternatives)
            else:
                if claims:
                    return {'action_id': claims[0]['id']}, {'source': 'fixed_reward_collection'}
                proceed = next((a for a in actions if a['kind'] == 'proceed'), None)
                if proceed:
                    return {'action_id': proceed['id']}, {'source': 'fixed_reward_progress', 'full_potion_belt_policy': 'skip_reward'}
        if surface is None:
            raise Unsupported(f'未対応の判断面: {state["phase"]}')
        base['type'] = surface
        packet = self.engine.ppo_wire_obs(base, surface)
        if packet is None or any(a['action'] == 'unknown' for a in packet['actions']):
            raise Unsupported(f'Mentorの入力ビルダーが候補を扱えない: {surface}')
        responses = []
        for response in packet['responses']:
            if response['action'] == 'choose':
                responses.append({'action_id': actions[response['index']]['id']})
            elif response['action'] == 'skip':
                responses.append({'action_id': next(a['id'] for a in actions if a['kind'] == 'reward_alternative')})
            else:
                raise Unsupported(f'Mentor応答が未対応: {response}')
        response, info = self.score(packet, responses)
        if surface == 'rest_site':
            info['fixed_excluded_rest_options'] = [metadata(a)['option_key'] for a in strategic_actions(observation)
                                                  if metadata(a)['option_key'] not in {'HEAL', 'SMITH'}]
        if surface == 'card_reward' and packet['actions'][info['chosen']].get('idx') is None:
            if self.card_reward_parent is not None:
                self.declined_card_rewards.add(self.card_reward_parent)
        return response, info

    def choose(self, boundary):
        started = time.monotonic()
        observation = boundary['observation']
        if boundary['decision_id'] == 1:
            self.declined_card_rewards = set()
            self.card_reward_parent = None
            self.reward_room = None
            self.context.reset()
            self.previous_combat = None
            self.last_signature = None
            self.repeated_decisions = 0
        original = observation
        observation = self.context.normalize(observation)
        room = self.room_key(observation)
        if room != self.reward_room:
            self.declined_card_rewards.clear()
            self.card_reward_parent = None
            self.reward_room = room
        if observation['capabilities']['gameVersion'] != 'v0.111.0':
            raise Unsupported('接続対象はv0.111.0のみ')
        previous = self.previous_combat
        self.previous_combat = None
        actions = strategic_actions(observation)
        if observation['state']['phase'] == 'grid_selection' and observation['state']['status']['combat'] is not None:
            if previous is None:
                raise Unsupported('戦闘子選択に対応する直前の公開行動がない')
            current = make_wire(observation, self.registries, self.engine)
            selection = observation['state']['selection']
            offered = [(resolve(card(c)['id'], self.registries['card'], ('_CARD', '_STATUS')),
                        bool(card(c)['upgrade_level'])) for c in selection['cards']]
            selection = dict(selection, max=min(selection['max'], len(offered)))
            state = resume_choice(self.engine, previous[0], previous[1], current, offered)
            pending = state.pending_choice()
            derived = [(c['id'], c['upgraded']) for c in pending['cards']]
            generative = self.engine.choice_kind_is_generative(pending['kind'])
            if generative:
                if any(card_state(c).get(k) for c in selection['cards'] for k in ('enchantment', 'affliction', 'special')):
                    raise Unsupported('生成候補に付与・特殊値があり、選択候補への注入が未対応')
                minimum = selection['min'] if pending['can_skip'] else pending['min_select']
                state.open_injected_choice(pending['kind'], [{'id': name, 'upgraded': upgraded} for name, upgraded in offered],
                    minimum, selection['max'], pending['can_skip'], True)
                pending = state.pending_choice()
                derived = [(c['id'], c['upgraded']) for c in pending['cards']]
            arity_matches = (selection['min'], selection['max']) == (pending['min_select'], pending['max_select'])
            curse_subset = pending['kind'] == 'monster_curse_select' and selection['min'] == 0 and selection['max'] == 1 and pending['min_select'] == pending['max_select'] == 1
            if offered != derived or not (arity_matches or curse_subset):
                raise Unsupported('子選択の候補・枚数が再生と一致しない')
            sims = self.search['boss_sims' if is_boss(observation) else 'sims']
            indices, searches = search_indices(self.engine, state, selection['min'], selection['max'],
                                               len(offered), sims=sims, threads=self.search['threads'])
            response, info = {'action_id': 'choose_cards:', 'indices': indices}, {
                    'source': 'mcts_verified_replay_choice', 'kind': pending['kind'],
                    'sims': sims, 'search_actions': searches, 'search_calls': len(searches),
                    'world_generated_options': generative, 'hidden_info': 'beliefdraw',
                    'choice_constraint': 'choose_one_curse_even_when_selector_allows_empty' if curse_subset else None}
        elif len(actions) == 1 and actions[0]['id'] != 'choose_cards:':
            response, info = {'action_id': actions[0]['id']}, {'source': 'single_candidate'}
        elif observation['state']['phase'] == 'combat':
            wire = make_wire(observation, self.registries, self.engine)
            state = self.engine.state_from_dict(wire)
            boss = is_boss(observation)
            result = self.engine.mcts_recommend(state, sims=self.search['boss_sims' if boss else 'sims'],
                        threads=self.search['threads'], hidden_info='beliefdraw', seed=0)
            matched = [(row, match_action(row['action'], observation)) for row in result['actions']]
            matched = [(row, action) for row, action in matched if action is not None]
            if not matched:
                raise Unsupported('MCTS提案に実ゲームの合法候補と対応するものがない')
            row, action = matched[0]
            self.previous_combat = wire, row['action']
            response, info = {'action_id': action['id']}, {'source': 'mcts_public_snapshot',
                'search_action': row['action'], 'unmapped_search_actions': len(result['actions']) - len(matched),
                'sims': self.search['boss_sims' if boss else 'sims'], 'hidden_info': 'beliefdraw',
                'enemy_move_assumptions': wire['public_ai_assumptions']}
        else:
            response, info = self.noncombat(observation)
        if observation['state']['phase'] == 'combat' and self.previous_combat is None:
            selected = next(a for a in actions if a['id'] == response['action_id'])
            if selected['kind'] != 'end_turn':
                raise Unsupported('唯一の戦闘候補を再生用の行動へ変換できない')
            self.previous_combat = make_wire(observation, self.registries, self.engine), {'action': 'end_turn'}
        selected = next(a for a in actions if a['id'] == response['action_id'])
        if selected['kind'] == 'reward' and metadata(selected).get('reward_type') == 'Card':
            self.card_reward_parent = selected['id']
        self.context.remember(observation, response)
        signature = hashlib.sha256(json.dumps([original, response], sort_keys=True).encode()).hexdigest()
        self.repeated_decisions = self.repeated_decisions + 1 if signature == self.last_signature else 1
        self.last_signature = signature
        if self.repeated_decisions > 3:
            raise Unsupported('同じ公開状態で同じ行動が3回続いても進まない')
        info.update(decision_id=boundary['decision_id'], phase=observation['state']['phase'],
                    seconds=time.monotonic()-started, response=response,
                    discard_potion_policy='keep',
                    out_of_combat_potion_policy='keep',
                    excluded_discard_candidates=sum(a['kind'] == 'discard_potion' for a in observation['actions']))
        print(json.dumps(info, ensure_ascii=False), file=sys.stderr, flush=True)
        return response

    def fallback_selection(self, boundary, error):
        observation = boundary['observation']
        state = observation['state']
        selection = state.get('selection')
        if not self.selection_fallback or state['phase'] != 'grid_selection' or selection is None:
            raise error
        if not any(a['id'] == 'choose_cards:' or a['detail'].get('parameter') == 'cardIndices'
                   for a in observation['actions']):
            raise error
        count = selection['min']
        if not 0 <= count <= min(selection['max'], len(selection['cards'])):
            raise error
        response = {'action_id': 'choose_cards:', 'indices': list(range(count))}
        signature = hashlib.sha256(json.dumps([observation, response], sort_keys=True).encode()).hexdigest()
        self.repeated_decisions = self.repeated_decisions + 1 if signature == self.last_signature else 1
        self.last_signature = signature
        if self.repeated_decisions > 3:
            raise Unsupported('固定子選択でも同じ公開状態が3回続いて進まない')
        print(json.dumps({'source': 'fixed_selection_fallback', 'reason': str(error),
                          'decision_id': boundary['decision_id'], 'phase': state['phase'],
                          'rule': 'first_required_indices; empty_when_optional',
                          'selection_effect_understood': False, 'response': response},
                         ensure_ascii=False), file=sys.stderr, flush=True)
        return response


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=default_config())
    parser.add_argument('--sims', type=int)
    parser.add_argument('--boss-sims', type=int)
    parser.add_argument('--allow-selection-fallback', action='store_true')
    args = parser.parse_args()
    policy = Mentor(args.config)
    policy.selection_fallback = args.allow_selection_fallback
    for key, value in [('sims', args.sims), ('boss_sims', args.boss_sims)]:
        if value is not None:
            if value <= 0:
                parser.error('探索回数は正の整数を指定')
            policy.search[key] = value
    print(json.dumps({'kind': 'policy_initialized', 'build_git': policy.engine.build_git(),
                      'selection_fallback': policy.selection_fallback,
                      'search': policy.search, 'config_sha256': sha(args.config),
                      'source_sha256': {name: sha(Path(__file__).parent / name) for name in
                          ['policy.py', 'combat.py', 'nested_combat.py', 'selection_context.py']}},
                     ensure_ascii=False), file=sys.stderr, flush=True)
    for line in sys.stdin:
        if line.strip():
            try:
                boundary = json.loads(line)
                try:
                    response = policy.choose(boundary)
                except Unsupported as error:
                    response = policy.fallback_selection(boundary, error)
            except Exception as error:
                traceback.print_exc(file=sys.stderr)
                response = {'error': str(error), 'error_type': type(error).__name__}
            print(json.dumps(response), flush=True)


if __name__ == '__main__':
    main()
