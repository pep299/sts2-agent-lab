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

    def test_invalid_conditions_are_rejected_instead_of_ignored_or_clamped(self):
        for values in [{}, {'event': '../AMALGAMATOR'}, {'event': 'AMALGAMATOR', 'goId': 9},
                       {'event': 'AMALGAMATOR', 'gold': True}, {'event': 'AMALGAMATOR', 'gold': -1},
                       {'event': 'AMALGAMATOR', 'hp': 5},
                       {'event': 'AMALGAMATOR', 'hp': 90, 'max_hp': 80},
                       {'event': 'AMALGAMATOR', 'hp': 0, 'max_hp': 80}]:
            with self.subTest(values=values), self.assertRaises(ValueError):
                event_fixture_parameters(values, fixture=True, save=None)
