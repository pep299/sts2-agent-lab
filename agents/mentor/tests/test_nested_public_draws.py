from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from agents.mentor.nested_combat import (
    align_public_boundary, checked_snapshot, condition_draws, public_projection, resume_choice,
)
from sts2.observation import Unsupported


PILES = {'draw': 'draw_pile', 'hand': 'hand', 'discard': 'discard_pile',
         'exhaust': 'exhaust_pile', 'play': 'play_pile'}


def card(damage=1, **extra):
    return dict(id='STRIKE_IRONCLAD', kind='card', upgraded=False, base_damage=damage, **extra)


def wire(cards):
    return {'deck': {'draw_pile': deepcopy(cards), 'hand': [], 'discard_pile': [],
                     'exhaust_pile': [], 'play_pile': [], 'master_deck': []},
            'player': {'hp': 10, 'max_hp': 10, 'block': 0, 'energy': 3, 'max_energy': 3,
                       'powers': [], 'relics': [], 'potions': []},
            'encounter': [], 'round': 1, 'turn': 1, 'side': 'Player',
            'public_instances': {}, 'public_draws': []}


def draw_event(instance, sequence=0):
    return {'card': {'id': 'CARD.STRIKE_IRONCLAD', 'instance': instance}, 'sequence': sequence}


class State:
    def __init__(self, source, engine):
        self.wire = deepcopy(source)
        self.engine = engine
        self.queue = []
        self.targets = []
        self.failed = False
        self.choice = None
        self.captured = None

    def __deepcopy__(self, memo):
        result = State({}, self.engine)
        result.wire, result.queue, result.targets, result.choice = deepcopy(
            (self.wire, self.queue, self.targets, self.choice), memo)
        result.failed = self.failed
        result.captured = self.captured
        return result

    def normalize_public_cards(self, cards):
        return deepcopy(cards)

    def condition_observed_draws(self, options):
        self.queue = [deepcopy(option) for option in options]
        self.targets = [self.wire['deck'][PILES[o['pile']]][o['index']] for o in options]
        self.failed = False

    def observed_draws_consumed(self):
        return not self.queue and not self.failed

    def pending_choice(self):
        return deepcopy(self.choice)

    def open_injected_choice(self, kind, options, low, high, skip, preserve):
        self.choice = dict(kind=kind, cards=deepcopy(options), min_select=low, max_select=high, can_skip=skip)

    def open_generated_choice(self, kind, options, low, high, skip):
        self.engine.generated.append((deepcopy(options), low, high, skip))
        self.open_injected_choice(kind, options, low, high, skip, True)

    def draw(self):
        if self.queue:
            self.queue.pop(0)
            chosen = self.targets.pop(0)
            if not any(c is chosen for c in self.wire['deck']['draw_pile']):
                self.failed = True
                return None
            position = next(i for i, card in enumerate(self.wire['deck']['draw_pile']) if card is chosen)
            self.wire['deck']['draw_pile'].pop(position)
        elif self.wire['deck']['draw_pile']:
            chosen = self.wire['deck']['draw_pile'].pop(0)
        else:
            return None
        self.wire['deck']['hand'].append(chosen)
        return chosen

    def apply(self, action):
        self.engine.transition(self, action)

    def resolve_public_choice(self, selection):
        self.apply({'action': 'choose', 'selection': selection})


class Engine:
    def __init__(self, transition=lambda *_: None):
        self.transition = transition
        self.generated = []
        self.draws = []

    def state_from_dict(self, value):
        return State(value, self)

    def state_to_dict(self, state):
        return deepcopy(state.wire)

    @staticmethod
    def choice_kind_is_generative(kind):
        return kind == 'generated'


def pending(state, low=1):
    state.open_injected_choice('discard', [{'id': 'STRIKE_IRONCLAD', 'upgraded': False,
                                          'pile': 'hand', 'index': 0}], low, 1, low == 0, True)


class PublicDrawHypotheses(unittest.TestCase):
    def test_decoder_cannot_drop_or_change_player_or_enemy_powers(self):
        for owner in ('player', 'enemy'):
            for change in ('drop', 'amount', 'display', 'counter'):
                with self.subTest(owner=owner, change=change):
                    source = wire([])
                    source['encounter'] = [{'powers': []}]
                    target = source['player'] if owner == 'player' else source['encounter'][0]
                    target['powers'] = [dict(name='PANACHE', amount=7, display=5, counter=2)]
                    class LossyEngine(Engine):
                        def state_to_dict(self, state):
                            result = super().state_to_dict(state)
                            target = result['player'] if owner == 'player' else result['encounter'][0]
                            if change == 'drop':
                                target['powers'].clear()
                            else:
                                target['powers'][0][change] = 99
                            return result
                    with self.assertRaisesRegex(Unsupported, 'Power'):
                        checked_snapshot(LossyEngine(), source)

    def test_decoder_cannot_drop_or_change_public_relic_state(self):
        for change in ('drop', 'id', 'counter', 'is_melted'):
            with self.subTest(change=change):
                source = wire([])
                source['player']['relics'] = [dict(id='PEN_NIB', counter=3, is_melted=True)]
                class LossyEngine(Engine):
                    def state_to_dict(self, state):
                        result = super().state_to_dict(state)
                        if change == 'drop':
                            result['player']['relics'].clear()
                        else:
                            result['player']['relics'][0][change] = 'wrong'
                        return result
                with self.assertRaisesRegex(Unsupported, 'レリック'):
                    checked_snapshot(LossyEngine(), source)

    def test_deck_metadata_is_not_parsed_as_cards_and_pins_preserve_ordered_meaning(self):
        source = wire([card(1), card(2)])
        source['deck'].update(pinned_top=[1, 0], pinned_bottom=[], deferred_draw_order=False)
        checked_snapshot(Engine(), source)
        class ReversePins(Engine):
            def state_to_dict(self, state):
                result = super().state_to_dict(state)
                result['deck']['pinned_top'].reverse()
                return result
        with self.assertRaisesRegex(Unsupported, '山札先頭'):
            checked_snapshot(ReversePins(), source)
        self.assertNotEqual(public_projection(source), public_projection(ReversePins().state_to_dict(State(source, Engine()))))
        source['deck']['draw_pile'] = [card(), card()]
        source['deck']['pinned_top'] = [1]
        current = deepcopy(source)
        current['public_draws'] = [draw_event(100)]
        states = list(condition_draws(Engine(), State(source, Engine()), source, current))
        self.assertEqual({s.queue[0]['index'] for s in states}, {0, 1})

    def test_generated_choice_constraints_are_checked_before_replacing_templates(self):
        engine = Engine()
        source = wire([])
        state = State(source, engine)
        state.open_injected_choice('generated', [card()], 1, 1, False, True)
        for low, high, skip, message in ((1, 2, False, '枚数'), (1, 1, True, 'skip可否')):
            with self.subTest(high=high, skip=skip):
                with self.assertRaisesRegex(Unsupported, message):
                    align_public_boundary(engine, state, [card()], low, high, skip)
        self.assertEqual(engine.generated, [])

    def test_same_name_different_attributes_are_tried_after_draw_hook_changes(self):
        def transition(state, action):
            selected = state.draw()
            if selected is None:
                return
            state.engine.draws.append(selected['base_damage'])
            selected['base_damage'] = 7
            pending(state)
        engine = Engine(transition)
        before = wire([card(1), card(2)])
        current = wire([card(1)])
        current['deck']['hand'] = [card(7)]
        current['public_draws'] = [draw_event(100)]
        saved = deepcopy(before)
        state, info = resume_choice(engine, before, {'action': 'play', 'card_index': 0}, current,
                                   [card(7)], minimum=1, maximum=1, can_skip=False)
        self.assertEqual(engine.draws, [1, 2])
        self.assertEqual(public_projection(state.wire), public_projection(current))
        self.assertEqual(info['attempts'], 2)
        self.assertEqual(before, saved)

    def test_later_boundary_failure_backtracks_an_earlier_matching_hypothesis(self):
        def transition(state, action):
            if action['action'] == 'play':
                selected = state.draw()
                state.captured = selected['base_damage']
                state.engine.draws.append(state.captured)
                for cards in state.wire['deck'].values():
                    for item in cards:
                        item['base_damage'] = 5
            else:
                state.wire['player']['hp'] -= state.captured
            pending(state)
        engine = Engine(transition)
        before = wire([card(1), card(2)])
        first = wire([card(5)])
        first['deck']['hand'] = [card(5)]
        first['public_draws'] = [draw_event(100)]
        final = deepcopy(first)
        final['player']['hp'] = 8
        history = [dict(current=first, cards=[card(5)], indices=[0], minimum=1, maximum=1, can_skip=False)]
        state, info = resume_choice(engine, before, {'action': 'play', 'card_index': 0}, final,
                                   [card(5)], history, minimum=1, maximum=1, can_skip=False)
        self.assertEqual(engine.draws, [1, 2])
        self.assertEqual(state.wire['player']['hp'], 8)
        self.assertEqual(info['earlier_choices'], 1)
        self.assertEqual(info['attempts'], 4)

    def test_identical_cards_collapse_permutations_but_preserve_multiplicity(self):
        engine = Engine()
        before = wire([card() for _ in range(20)])
        current = deepcopy(before)
        current['public_draws'] = [draw_event(100), draw_event(101, 1)]
        states = list(condition_draws(engine, engine.state_from_dict(before), before, current))
        self.assertEqual(len(states), 1)
        self.assertEqual([o['index'] for o in states[0].queue], [0, 1])

    def test_identical_cards_in_different_piles_are_not_legality_equivalent(self):
        engine = Engine()
        before = wire([card()])
        before['deck']['hand'] = [card()]
        current = deepcopy(before)
        current['public_draws'] = [draw_event(100)]
        states = list(condition_draws(engine, engine.state_from_dict(before), before, current))
        self.assertEqual({s.queue[0]['pile'] for s in states}, {'draw', 'hand'})

    def test_known_instance_keeps_its_index_and_cannot_bind_an_anonymous_identity(self):
        engine = Engine()
        before = wire([card()])
        before['deck']['discard_pile'] = [card(), card()]
        before['public_instances'] = {'90': {'pile': 'discard', 'index': 1}}
        current = deepcopy(before)
        current['public_draws'] = [draw_event(100), draw_event(90, 1)]
        states = list(condition_draws(engine, engine.state_from_dict(before), before, current))
        self.assertTrue(states)
        self.assertTrue(all(s.queue[-1]['index'] == 1 and s.queue[-1]['pile'] == 'discard' for s in states))
        self.assertTrue(all(s.queue[0] != s.queue[-1] for s in states))
        before['deck']['discard_pile'][1]['base_damage'] = 99
        with self.assertRaisesRegex(Unsupported, '既知個体'):
            list(condition_draws(engine, engine.state_from_dict(current), before, current))

    def test_modifier_lifetimes_are_distinct_even_with_equal_current_prices(self):
        cards = [card(local_cost={'base': 1, 'costs_x': False, 'modifiers': [
            {'kind': 'absolute', 'amount': 0, 'reduce_only': False, 'expiration': expiry}]}) for expiry in (2, 4)]
        engine = Engine()
        before = wire(cards)
        current = deepcopy(before)
        current['public_draws'] = [draw_event(100)]
        self.assertEqual(len(list(condition_draws(engine, engine.state_from_dict(before), before, current))), 2)

    def test_an_illegal_first_draw_hypothesis_does_not_accept_the_state(self):
        def transition(state, action):
            state.wire['deck']['draw_pile'], state.wire['deck']['hand'] = state.wire['deck']['hand'], []
            selected = state.draw()
            if selected is not None:
                pending(state)
        engine = Engine(transition)
        before = wire([card()])
        before['deck']['hand'] = [card()]
        current = wire([])
        current['deck']['hand'] = [card()]
        current['public_draws'] = [draw_event(100)]
        state, info = resume_choice(engine, before, {'action': 'play', 'card_index': 0}, current, [card()])
        self.assertFalse(state.failed)
        self.assertEqual(info['attempts'], 2)

    def test_final_candidate_arity_rejects_the_first_matching_board(self):
        def transition(state, action):
            selected = state.draw()
            damage = selected['base_damage']
            for cards in state.wire['deck'].values():
                for item in cards:
                    item['base_damage'] = 5
            pending(state, damage - 1)
        engine = Engine(transition)
        before = wire([card(1), card(2)])
        current = wire([card(5)])
        current['deck']['hand'] = [card(5)]
        current['public_draws'] = [draw_event(100)]
        state, info = resume_choice(engine, before, {'action': 'play', 'card_index': 0}, current,
                                   [card(5)], minimum=1, maximum=1, can_skip=False)
        self.assertEqual(state.pending_choice()['min_select'], 1)
        self.assertEqual(info['attempts'], 2)

    def test_generated_history_replaces_only_public_options_then_replays_the_choice(self):
        def transition(state, action):
            if action['action'] == 'play':
                state.open_injected_choice('generated', [{'id': 'UNKNOWN', 'upgraded': False}], 1, 1, False, True)
            else:
                state.wire['deck']['hand'].append(deepcopy(state.choice['cards'][action['selection'][0]]))
                pending(state)
        engine = Engine(transition)
        before = wire([])
        first = deepcopy(before)
        final = deepcopy(before)
        final['deck']['hand'] = [card(7)]
        history = [dict(current=first, cards=[card(7)], indices=[0], minimum=1, maximum=1, can_skip=False)]
        state, _ = resume_choice(engine, before, {'action': 'play', 'card_index': 0}, final,
                                 [card(7)], history, minimum=1, maximum=1, can_skip=False)
        self.assertEqual(engine.generated, [([card(7)], 1, 1, False)])
        self.assertEqual(state.wire['deck']['hand'], [card(7)])

    def test_candidate_attributes_and_skip_permission_are_checked(self):
        engine = Engine()
        source = wire([])
        source['deck']['hand'] = [card()]
        state = engine.state_from_dict(source)
        pending(state)
        with self.assertRaisesRegex(Unsupported, '属性が再生中'):
            align_public_boundary(engine, state, [card(9)], 1, 1, False)
        with self.assertRaisesRegex(Unsupported, 'skip可否'):
            align_public_boundary(engine, state, [card()], 1, 1, True)

    def test_revealed_random_subset_is_conditioned_only_within_its_actual_pile(self):
        engine = Engine()
        source = wire([card(1), card(2), card(3)])
        state = engine.state_from_dict(source)
        options = [dict(id=c['id'], upgraded=False, pile='draw', index=i)
                   for i, c in enumerate(source['deck']['draw_pile'][:2])]
        state.open_injected_choice('add_from_random_draw_subset', options, 1, 1, False, True)
        align_public_boundary(engine, state, [card(2), card(3)], 1, 1, False)
        self.assertEqual([c['index'] for c in state.pending_choice()['cards']], [1, 2])
        self.assertEqual(state.wire['deck'], source['deck'])
        with self.assertRaisesRegex(Unsupported, '属性が再生中'):
            align_public_boundary(engine, state, [card(2), card(9)], 1, 1, False)
        with self.assertRaisesRegex(Unsupported, '候補の枚数'):
            align_public_boundary(engine, state, [card(2)], 1, 1, False)
        state.open_injected_choice('add_from_draw_by_type', options, 1, 1, False, True)
        with self.assertRaisesRegex(Unsupported, '属性が再生中'):
            align_public_boundary(engine, state, [card(2), card(3)], 1, 1, False)


if __name__ == '__main__':
    unittest.main()
