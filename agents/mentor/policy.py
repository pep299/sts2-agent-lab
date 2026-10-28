"""公開観測と合法候補からMentorの戦闘探索・非戦闘方策を選ぶ。"""
import hashlib
import json
import sys
import time

from agents.mentor.combat import make_wire, match_action, wire_cards
from agents.mentor.crystal import choose as choose_crystal
from agents.mentor.nested_combat import align_public_boundary, apply_public_action, checked_snapshot, resume_choice, search_indices
from agents.mentor.noncombat import NoncombatPolicy, UnscoredSelection, card, strategic_actions
from agents.mentor.runtime import MentorRuntime
from sts2.observation import Unsupported, is_boss
from sts2.selection import SelectionContext


class Mentor:
    def __init__(self, configuration):
        runtime = MentorRuntime(configuration)
        self.identity = runtime.identity
        self.engine = runtime.engine
        self.search = runtime.search
        self.registries = runtime.registries
        self.noncombat = NoncombatPolicy(runtime)
        self.context = SelectionContext()
        self.previous_combat = None
        self.last_signature = None
        self.repeated_decisions = 0
        self.selection_fallback = False

    def choose(self, boundary):
        started = time.monotonic()
        observation = boundary['observation']
        if boundary['decision_id'] == 1:
            self.noncombat.reset()
            self.context.reset()
            self.previous_combat = None
            self.last_signature = None
            self.repeated_decisions = 0
        original = observation
        observation = self.context.prepare(observation)
        self.noncombat.prepare(observation)
        if observation['capabilities']['gameVersion'] != 'v0.111.0':
            raise Unsupported('接続対象はv0.111.0のみ')
        previous = self.previous_combat
        self.previous_combat = None
        actions = strategic_actions(observation)
        if observation['state']['phase'] == 'grid_selection' and observation['state']['status']['combat'] is not None:
            current = make_wire(observation, self.registries, self.engine)
            selection = observation['state']['selection']
            candidates = wire_cards(selection['cards'], self.registries)
            offered = [(c['id'], c['upgraded']) for c in candidates]
            selection = dict(selection, max=min(selection['max'], len(offered)))
            context = selection.get('context') or {}
            source = context.get('source') or {}
            if source.get('kind') == 'relic':
                relic = source['modelId'].split('.', 1)[-1]
                expected_hook = {'TOOLBOX': 'BeforeHandDraw', 'TOASTY_MITTENS': 'AfterPlayerTurnStart',
                                 'GAMBLING_CHIP': 'AfterPlayerTurnStart', 'CHOICES_PARADOX': 'AfterPlayerTurnStart'}
                if relic not in expected_hook or source.get('hook') != expected_hook[relic]:
                    raise Unsupported('開始選択元のレリックとhookが対応しない')
                state, _ = checked_snapshot(self.engine, current)
                action = {'action': 'start_relic_choice', 'relic': relic}
                apply_public_action(state, action)
                align_public_boundary(self.engine, state, candidates,
                    selection['min'], selection['max'], context.get('canSkip'))
                previous = current, action
                history = []
                replay_info = {'method': 'public_relic_start_choice', 'relic': relic, 'hook': source['hook']}
            else:
                if previous is None:
                    raise Unsupported('戦闘子選択に対応する直前の公開行動がない')
                history = previous[2] if len(previous) > 2 else []
                state, replay_info = resume_choice(self.engine, previous[0], previous[1], current, candidates, history,
                    minimum=selection['min'], maximum=selection['max'], can_skip=context.get('canSkip'))
            pending = state.pending_choice()
            generative = self.engine.choice_kind_is_generative(pending['kind'])
            constrained = selection['min'] < pending['min_select']
            sims = self.search['boss_sims' if is_boss(observation) else 'sims']
            indices, searches = search_indices(self.engine, state, selection['min'], selection['max'],
                                               len(offered), sims=sims, threads=self.search['threads'])
            self.previous_combat = previous[0], previous[1], history + [
                {'current': current, 'cards': candidates, 'indices': indices,
                 'minimum': selection['min'], 'maximum': selection['max'], 'can_skip': pending['can_skip']}]
            response, info = {'action_id': 'choose_cards:', 'indices': indices}, {
                    'source': 'mcts_verified_replay_choice', 'kind': pending['kind'],
                    'sims': sims, 'search_actions': searches, 'search_calls': len(searches),
                    'replay': replay_info,
                    'world_generated_options': generative, 'hidden_info': 'beliefdraw',
                    'choice_constraint': 'choose_one_curse_even_when_selector_allows_empty' if constrained else None}
        elif observation['state']['phase'] == 'crystal_sphere':
            response, info = choose_crystal(dict(observation, actions=actions))
        elif len(actions) == 1 and actions[0]['id'] != 'choose_cards:':
            response, info = {'action_id': actions[0]['id']}, {'source': 'single_candidate'}
        elif observation['state']['phase'] == 'combat':
            wire = make_wire(observation, self.registries, self.engine)
            state, _ = checked_snapshot(self.engine, wire)
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
            response, info = self.noncombat.choose(observation)
        if observation['state']['phase'] == 'combat' and self.previous_combat is None:
            selected = next(a for a in actions if a['id'] == response['action_id'])
            if selected['kind'] != 'end_turn':
                raise Unsupported('唯一の戦闘候補を再生用の行動へ変換できない')
            self.previous_combat = make_wire(observation, self.registries, self.engine), {'action': 'end_turn'}
        self.noncombat.remember(observation, response)
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
                    excluded_shop_close_candidates=sum(a['kind'] == 'shop_close' for a in observation['actions']),
                    excluded_discard_candidates=sum(a['kind'] == 'discard_potion' for a in observation['actions']))
        print(json.dumps(info, ensure_ascii=False), file=sys.stderr, flush=True)
        return response


    def fallback_selection(self, boundary, error):
        observation = boundary['observation']
        state = observation['state']
        selection = state.get('selection')
        if (not self.selection_fallback or not isinstance(error, UnscoredSelection)
                or state['phase'] != 'grid_selection' or selection is None):
            raise error
        if not any(a['id'] == 'choose_cards:'
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
