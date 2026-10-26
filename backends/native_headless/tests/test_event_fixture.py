import unittest

from runtime import event_fixture_parameters


class EventFixtureParametersTests(unittest.TestCase):
    def test_absent_fixture_does_not_change_normal_start_request(self):
        self.assertEqual(event_fixture_parameters(None, fixture=False, save=None), {})

    def test_fixture_start_preserves_requested_conditions(self):
        parameters = event_fixture_parameters(
            {'event': 'AMALGAMATOR', 'hp': 40, 'max_hp': 80, 'gold': 0}, fixture=True, save=None)
        self.assertEqual(parameters, {'fixture_event': 'AMALGAMATOR', 'fixture_hp': 40,
                                      'fixture_max_hp': 80, 'fixture_gold': 0})

    def test_fixture_cannot_be_applied_to_normal_or_restored_runs(self):
        for fixture, save in [(False, None), (True, 'current_run.save')]:
            with self.subTest(fixture=fixture, save=save), self.assertRaises(ValueError):
                event_fixture_parameters({'event': 'AMALGAMATOR'}, fixture=fixture, save=save)

    def test_conditional_fixture_preserves_act_potion_slots_and_deck_intent(self):
        settings = {'event': 'SELF_HELP_BOOK', 'act': 2, 'potions': [None, 'FIRE_POTION'],
                    'add_cards': ['INFLAME'], 'deck': [], 'relics': ['VAJRA']}
        self.assertEqual(event_fixture_parameters(settings, fixture=True, save=None),
                         {'fixture_' + key: value for key, value in settings.items()})

    def test_invalid_conditions_are_rejected_instead_of_ignored_or_clamped(self):
        for values in [{}, {'event': '../AMALGAMATOR'}, {'event': 'AMALGAMATOR', 'goId': 9},
                       {'event': 'AMALGAMATOR', 'gold': True}, {'event': 'AMALGAMATOR', 'gold': -1},
                       {'event': 'AMALGAMATOR', 'hp': 5},
                       {'event': 'AMALGAMATOR', 'hp': 90, 'max_hp': 80},
                       {'event': 'AMALGAMATOR', 'hp': 0, 'max_hp': 80},
                       {'event': 'SELF_HELP_BOOK', 'act': True},
                       {'event': 'SELF_HELP_BOOK', 'act': 4},
                       {'event': 'SELF_HELP_BOOK', 'potions': 'FIRE_POTION'},
                       {'event': 'SELF_HELP_BOOK', 'add_cards': [None]},
                       {'event': 'SELF_HELP_BOOK', 'relics': ['RELIC.VAJRA']},
                       {'event': 'SELF_HELP_BOOK', 'deck': [True]}]:
            with self.subTest(values=values), self.assertRaises(ValueError):
                event_fixture_parameters(values, fixture=True, save=None)

    def test_architect_requires_explicit_final_act_context(self):
        for act in (None, 1, 2):
            with self.subTest(act=act), self.assertRaises(ValueError):
                event_fixture_parameters({'event': 'THE_ARCHITECT', **({'act': act} if act else {})}, fixture=True, save=None)
        self.assertEqual(event_fixture_parameters({'event': 'THE_ARCHITECT', 'act': 3}, fixture=True, save=None),
                         {'fixture_event': 'THE_ARCHITECT', 'fixture_act': 3})
