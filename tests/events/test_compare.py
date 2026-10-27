import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('compare_events', Path(__file__).with_name('compare.py'))
checks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checks)


def card(name='CARD.DEFEND', **changes):
    return {'id': name, 'upgrade': 0, 'keywords': [], 'enchantment': None,
            'affliction': None, 'special': None, 'instance': 1,
            'facts': {'title': 'Rendered title', 'rules': {'text': 'Rendered rules'},
                      'type': 'Skill', 'rarity': 'Basic', 'targetType': 'Self',
                      'energyCost': {'canonical': 1, 'costsX': False, 'current': 1},
                      'starCost': {'current': -1, 'costsX': False},
                      'dynamicVars': [{'name': 'Block', 'baseValue': 5, 'enchantedValue': 5, 'previewValue': 5}],
                      'retain': False, 'sly': False}, **changes}


def state():
    return {'hp': 40, 'maxHp': 80, 'gold': 100, 'act': 1, 'floor': 1, 'phase': 'event',
            'terminal': None, 'deck': [card(), card('CARD.STRIKE')], 'relics': ['BURNING_BLOOD'],
            'relicDetails': [{'id': 'BURNING_BLOOD', 'showCounter': False, 'counter': None,
                              'stackCount': 1, 'isMelted': False, 'isUsedUp': False, 'dynamicVars': []}],
            'potions': {'capacity': 2, 'slots': [{'index': 0, 'potion': None}, {'index': 1, 'potion': None}]}}


def candidate(key='EVENT.pages.INITIAL.options.A', relic=None, index=0, action='event:0'):
    return {'key': key, 'relic': relic, 'option_index': index, 'action_id': action}


def trace(offered=None, chosen=None):
    offered = offered or [candidate()]
    return {'phase': 'event', 'candidates': offered,
            'response': {'action_id': chosen or offered[0]['action_id']}}


def record():
    return {'event': {'name': 'Example', 'id': 'EVENT.EXAMPLE'}, '_identity': 'EVENT.EXAMPLE',
            '_source': 'case.json', '_sha256': 'a' * 64,
            'fixture': True, 'expertData': False, 'status': 'completed',
            'initialCondition': {'seed': 'SAME', 'hp': 40, 'maxHp': 80, 'gold': 100},
            'before': state(), 'after': state() | {'phase': 'map'}, 'trace': [trace()]}


def save(root, contents, name='000'):
    path = root / 'Example' / name / 'case.json'
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(contents))


class EventComparison(unittest.TestCase):
    def test_localized_text_instance_ids_and_deck_order_are_ignored(self):
        learn, native = record(), record()
        native['before']['deck'].reverse()
        native['after']['deck'][0].update(instance=987, rendered='表示')
        native['after']['deck'][0]['facts'].update(title='日本語', rules={'text': '日本語ルール'})
        native['trace'][0]['candidates'][0]['action_id'] = 'native:option:0'
        native['trace'][0]['response']['action_id'] = 'native:option:0'
        result = checks.compare_records(learn, native)
        self.assertEqual(result['status'], 'recorded_fields_match')
        self.assertFalse(result['semanticEffectVerified'])

    def test_amount_changes_in_card_modifiers_are_not_ignored(self):
        for field in ('enchantment', 'affliction', 'special'):
            with self.subTest(field=field):
                learn, native = record(), record()
                learn['after']['deck'][0][field] = {'id': 'MODIFIER', 'amount': 1}
                native['after']['deck'][0][field] = {'id': 'MODIFIER', 'amount': 2}
                result = checks.compare_records(learn, native)
                self.assertEqual(result['status'], 'recorded_state_mismatch')
                self.assertIn('deck', result['differences']['finalPublicState'])

    def test_initial_difference_blocks_matching_final_state(self):
        learn, native = record(), record()
        native['before']['gold'] = 101
        result = checks.compare_records(learn, native)
        self.assertEqual(result['status'], 'initial_state_mismatch')

    def test_duplicate_card_counts_are_preserved(self):
        learn, native = record(), record()
        native['after']['deck'].append(card())
        result = checks.compare_records(learn, native)
        self.assertEqual(result['status'], 'recorded_state_mismatch')
        self.assertEqual(len(result['effects']['native']['deck']['added']), 1)

    def test_potion_slot_order_is_ignored_but_slot_contents_are_preserved(self):
        learn, native = record(), record()
        native['after']['potions']['slots'].reverse()
        self.assertEqual(checks.compare_records(learn, native)['status'], 'recorded_fields_match')
        native['after']['potions']['slots'][0]['potion'] = {'id': 'POTION.FIRE', 'queued': False}
        self.assertEqual(checks.compare_records(learn, native)['status'], 'recorded_state_mismatch')

    def test_numeric_card_facts_and_cost_changes_are_compared(self):
        for change in ('block', 'cost', 'star_cost', 'retain', 'sly', 'type', 'rarity', 'targetType'):
            with self.subTest(change=change):
                learn, native = record(), record()
                facts = native['after']['deck'][0]['facts']
                if change == 'block':
                    facts['dynamicVars'][0]['baseValue'] = 6
                elif change == 'cost':
                    facts['energyCost']['current'] = 0
                elif change == 'star_cost':
                    facts['starCost']['current'] = 2
                elif change in ('retain', 'sly'):
                    facts[change] = True
                else:
                    facts[change] = 'DIFFERENT'
                result = checks.compare_records(learn, native)
                self.assertEqual(result['status'], 'recorded_state_mismatch')
                self.assertIn('deck', result['differences']['finalPublicState'])

    def test_dynamic_vars_are_matched_by_name_and_not_publication_order(self):
        learn, native = record(), record()
        extra = {'name': 'Other', 'baseValue': 3, 'enchantedValue': 3, 'previewValue': 3}
        for contents in (learn, native):
            contents['after']['deck'][0]['facts']['dynamicVars'].append(copy.deepcopy(extra))
        native['after']['deck'][0]['facts']['dynamicVars'].reverse()
        self.assertEqual(checks.compare_records(learn, native)['status'], 'recorded_fields_match')
        native['after']['deck'][0]['facts']['dynamicVars'][0]['previewValue'] = 4
        self.assertEqual(checks.compare_records(learn, native)['status'], 'recorded_state_mismatch')

    def test_missing_card_facts_or_a_missing_published_value_prevents_a_match(self):
        for missing in ('facts', 'energyCost', 'current', 'dynamicValue'):
            with self.subTest(missing=missing):
                learn, native = record(), record()
                value = native['after']['deck'][0]
                if missing == 'facts':
                    del value['facts']
                elif missing == 'energyCost':
                    del value['facts']['energyCost']
                elif missing == 'current':
                    del value['facts']['energyCost']['current']
                else:
                    del value['facts']['dynamicVars'][0]['previewValue']
                self.assertEqual(checks.compare_records(learn, native)['status'], 'public_fields_missing')

    def test_missing_relic_details_on_both_sides_is_explicitly_uncompared(self):
        learn, native = record(), record()
        for contents in (learn, native):
            del contents['before']['relicDetails']
            del contents['after']['relicDetails']
        result = checks.compare_records(learn, native)
        self.assertEqual(result['status'], 'public_fields_missing')
        self.assertIn('learnBeforeRelicDetailsMissing', result['differences'])
        self.assertIn('nativeAfterRelicDetailsMissing', result['differences'])
        self.assertFalse(result['effects']['learn']['relicDetails']['compared'])

    def test_relic_counter_stack_used_state_and_dynamic_values_are_compared(self):
        for field in ('showCounter', 'counter', 'stackCount', 'isMelted', 'isUsedUp', 'dynamicVars'):
            with self.subTest(field=field):
                learn, native = record(), record()
                relic = native['after']['relicDetails'][0]
                if field == 'dynamicVars':
                    relic[field] = [{'name': 'Amount', 'baseValue': 1, 'enchantedValue': 1, 'previewValue': 1}]
                elif field in ('counter', 'stackCount'):
                    relic[field] = 2
                else:
                    relic[field] = True
                self.assertEqual(checks.compare_records(learn, native)['status'], 'recorded_state_mismatch')

    def test_relic_detail_missing_on_one_side_or_inconsistent_with_ids_is_not_a_match(self):
        for mode in ('missing_details', 'missing_counter', 'missing_entry'):
            with self.subTest(mode=mode):
                learn, native = record(), record()
                if mode == 'missing_details':
                    del native['after']['relicDetails']
                elif mode == 'missing_counter':
                    del native['after']['relicDetails'][0]['counter']
                else:
                    native['after']['relicDetails'] = []
                self.assertEqual(checks.compare_records(learn, native)['status'], 'public_fields_missing')

    def test_only_single_proceed_without_relic_is_separated(self):
        learn, native = record(), record()
        native['trace'].append(trace([candidate('PROCEED')]))
        result = checks.compare_records(learn, native)
        self.assertEqual(result['status'], 'recorded_fields_match')
        self.assertIn('boundaryShapeDifferences', result)
        self.assertEqual(len(result['boundaryShapeDifferences']['native']), 1)
        native['trace'][-1]['candidates'][0]['relic'] = 'ACTUAL_REWARD'
        self.assertEqual(len(checks.event_path(native)[0]), 2)
        native['trace'][-1] = trace([candidate('PROCEED'), candidate('OTHER', index=1, action='event:1')])
        self.assertEqual(len(checks.event_path(native)[0]), 2)

    def test_same_event_key_different_relic_or_index_is_a_different_branch(self):
        original = record()
        for replacement in [candidate(relic='OTHER'), candidate(index=1)]:
            modified = record()
            modified['trace'][0] = trace([replacement])
            self.assertNotEqual(checks.event_path(original)[0], checks.event_path(modified)[0])

    def test_incomplete_or_missing_state_is_never_a_match(self):
        learn, native = record(), record()
        for contents in (learn, native):
            contents['status'] = 'fault'
            contents.pop('after')
        self.assertEqual(checks.compare_records(learn, native)['status'], 'execution_incomplete')
        learn, native = record(), record()
        learn['before']['deck'][0].pop('upgrade')
        self.assertEqual(checks.compare_records(learn, native)['status'], 'public_fields_missing')

    def test_declared_seed_difference_is_not_treated_as_random_tolerance(self):
        learn, native = record(), record()
        native['initialCondition']['seed'] = 'DIFFERENT'
        self.assertEqual(checks.compare_records(learn, native)['status'], 'initial_condition_mismatch')

    def test_unselected_candidate_difference_is_reported(self):
        learn, native = record(), record()
        native['trace'][0]['candidates'].append(candidate('RANDOM_OTHER', index=1, action='other'))
        result = checks.compare_records(learn, native)
        self.assertEqual(result['status'], 'recorded_state_mismatch')
        self.assertIn('eventCandidates', result['differences'])

    def test_missing_paths_and_unexecuted_endgame_context_are_retained(self):
        with tempfile.TemporaryDirectory() as directory:
            learn, native = Path(directory) / 'learn', Path(directory) / 'native'
            learn.mkdir(); native.mkdir()
            save(learn, record())
            (native / 'summary.json').write_text(json.dumps({'cases': [
                {'event': 'TheArchitect', 'status': 'unsupported_fixture', 'reason': 'requires endgame context'}]}))
            report = checks.compare(learn, native)
            self.assertEqual(report['counts'], {'missing_case': 1})
            self.assertEqual(report['coverageGaps']['native'][0]['event'], 'TheArchitect')
            self.assertEqual(report['emptyInputs'], ['native'])
            self.assertFalse(report['allBranchesVerified'])

    def test_duplicate_paths_are_ambiguous_instead_of_arbitrarily_paired(self):
        with tempfile.TemporaryDirectory() as directory:
            learn, native = Path(directory) / 'learn', Path(directory) / 'native'
            learn.mkdir(); native.mkdir()
            save(learn, record()); save(learn, record(), '001'); save(native, record())
            self.assertEqual(checks.compare(learn, native)['counts'], {'ambiguous_pair': 1})

    def test_missing_failed_case_referenced_by_summary_is_not_silently_dropped(self):
        with tempfile.TemporaryDirectory() as directory:
            learn, native = Path(directory) / 'learn', Path(directory) / 'native'
            learn.mkdir(); native.mkdir()
            save(learn, record()); save(native, record())
            (native / 'summary.json').write_text(json.dumps({'cases': [
                {'event': 'Example', 'case': 'Example/000', 'status': 'completed'},
                {'event': 'Example', 'case': 'Example/001', 'status': 'fault'}]}))
            report = checks.compare(learn, native)
            self.assertEqual(report['counts'], {'recorded_fields_match': 1})
            self.assertEqual(len(report['readErrors']['native']), 1)
            self.assertEqual(report['readErrors']['native'][0]['case'], 'Example/001')

    def test_summary_status_and_case_status_must_agree(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            save(root, record())
            (root / 'summary.json').write_text(json.dumps({'cases': [
                {'event': 'Example', 'case': 'Example/000', 'status': 'fault'}]}))
            _, _, errors = checks.load_cases(root)
            self.assertEqual(len(errors), 1)
            self.assertIn('一致しない', errors[0]['error'])

    def test_candidate_response_must_have_an_unambiguous_public_match(self):
        contents = record()
        contents['trace'][0]['response']['action_id'] = 'not_offered'
        with self.assertRaisesRegex(ValueError, '公開候補'):
            checks.event_path(contents)

    def test_output_file_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            existing = root / 'result.json'; existing.write_text('preserve')
            result = subprocess.run([sys.executable, str(Path(checks.__file__)), '--learn', str(root),
                                     '--native', str(root), '--output', str(existing)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(existing.read_text(), 'preserve')


if __name__ == '__main__':
    unittest.main()
