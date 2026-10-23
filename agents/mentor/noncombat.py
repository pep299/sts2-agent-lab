"""MentorのPPO入力・候補変換と、非戦闘の行動選択規則。"""
import math
from sts2.observation import Unsupported, card_state, metadata


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


class NoncombatPolicy:
    def __init__(self, runtime):
        self.engine = runtime.engine
        self.net = runtime.net
        self.selection_fallback = False
        self.reset()

    def reset(self):
        self.declined_card_rewards = set()
        self.card_reward_parent = None
        self.reward_room = None

    def prepare(self, observation):
        status = observation['state']['status']
        room = status['act'], status['floor']
        if room != self.reward_room:
            self.declined_card_rewards.clear()
            self.card_reward_parent = None
            self.reward_room = room

    def remember(self, observation, response):
        selected = next(a for a in observation['actions'] if a['id'] == response['action_id'])
        if selected['kind'] == 'reward' and metadata(selected).get('reward_type') == 'Card':
            self.card_reward_parent = selected['id']

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
                obs['pending_enchantment'] = selection.get('enchantment')
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


    def choose(self, observation):
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
                response, info = self.choose(shop)
                if response['action_id'] != 'mentor:leave_shop':
                    return response, info
                move = dict(observation, state=dict(state, phase='map'), actions=destinations)
                response, map_info = self.choose(move)
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
            collections = [a for a in claims if 'reward_type' in metadata(a)]
            if collections:
                return {'action_id': collections[0]['id']}, {'source': 'fixed_reward_collection'}
            cards = [a for a in actions if 'card_id' in metadata(a)]
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
