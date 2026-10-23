"""公開観測と合法候補からMentorの戦闘探索・非戦闘方策を選ぶ。"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
import traceback

from agents.mentor.combat import make_wire, match_action, resolve
from agents.mentor.nested_combat import resume_choice, search_indices
from agents.mentor.noncombat import NoncombatPolicy, card, strategic_actions
from agents.mentor.runtime import MentorRuntime, REPO, default_config, sha
from sts2.observation import Unsupported, card_state, is_boss
from sts2.selection import SelectionContext


class Mentor:
    def __init__(self, configuration):
        runtime = MentorRuntime(configuration)
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
        self.noncombat.selection_fallback = self.selection_fallback
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
                    excluded_discard_candidates=sum(a['kind'] == 'discard_potion' for a in observation['actions']))
        print(json.dumps(info, ensure_ascii=False), file=sys.stderr, flush=True)
        return response


    def fallback_selection(self, boundary, error):
        observation = boundary['observation']
        state = observation['state']
        selection = state.get('selection')
        if not self.selection_fallback or state['phase'] != 'grid_selection' or selection is None:
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
    sources = [REPO / name for name in (
        'agents/mentor/policy.py', 'agents/mentor/runtime.py', 'agents/mentor/noncombat.py',
        'agents/mentor/combat.py', 'agents/mentor/nested_combat.py',
        'sts2/observation.py', 'sts2/selection.py')]
    print(json.dumps({'kind': 'policy_initialized', 'build_git': policy.engine.build_git(),
                      'selection_fallback': policy.selection_fallback,
                      'search': policy.search, 'config_sha256': sha(args.config),
                      'source_sha256': {str(path.relative_to(REPO)): sha(path) for path in sources}},
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
