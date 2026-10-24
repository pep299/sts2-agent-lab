"""実行済みイベント分岐の公開状態を、learnとnativeの記録で照合する。"""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path


STATE_FIELDS = ('hp', 'maxHp', 'gold', 'act', 'floor', 'phase', 'terminal', 'deck', 'relics', 'potions')
CARD_FIELDS = ('id', 'upgrade', 'keywords', 'enchantment', 'affliction', 'special')
CARD_FACT_FIELDS = ('type', 'rarity', 'targetType', 'energyCost', 'starCost', 'dynamicVars', 'retain', 'sly')
RELIC_FIELDS = ('id', 'showCounter', 'counter', 'stackCount', 'isMelted', 'isUsedUp', 'dynamicVars')
IGNORED_PRESENTATION = {'title', 'rules', 'description', 'rendered', 'instance', 'identityScope'}


def serialized(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def without_presentation(value):
    if isinstance(value, dict):
        return {key: without_presentation(item) for key, item in value.items() if key not in IGNORED_PRESENTATION}
    if isinstance(value, list):
        return [without_presentation(item) for item in value]
    return value


def require_fields(value, fields, path):
    if not isinstance(value, dict):
        raise ValueError(path + 'はobjectである必要がある')
    missing = set(fields) - value.keys()
    if missing:
        raise ValueError(path + 'に必要なフィールドがない: ' + ', '.join(sorted(missing)))


def dynamic_vars(values, path):
    if not isinstance(values, list):
        raise ValueError(path + 'はlistである必要がある')
    for value in values:
        require_fields(value, ('name', 'baseValue', 'enchantedValue', 'previewValue'), path)
    names = [value['name'] for value in values]
    if any(not isinstance(name, str) for name in names) or len(names) != len(set(names)):
        raise ValueError(path + 'のnameが文字列でないか重複している')
    return sorted((without_presentation(value) for value in values), key=lambda value: value['name'])


def canonical_state(state):
    missing = set(STATE_FIELDS) - state.keys()
    if missing:
        raise ValueError('公開状態に必要なフィールドがない: ' + ', '.join(sorted(missing)))
    result = {key: state[key] for key in STATE_FIELDS}
    deck = []
    for card in state['deck']:
        missing = set(CARD_FIELDS) - card.keys()
        if missing:
            raise ValueError('カード状態に必要なフィールドがない: ' + ', '.join(sorted(missing)))
        normalized = {key: without_presentation(card[key]) for key in CARD_FIELDS}
        normalized['keywords'] = sorted(normalized['keywords'], key=serialized)
        facts = card.get('facts')
        require_fields(facts, CARD_FACT_FIELDS, 'card.facts')
        normalized['facts'] = {key: without_presentation(facts[key]) for key in CARD_FACT_FIELDS}
        require_fields(facts['energyCost'], ('canonical', 'costsX', 'current'), 'card.facts.energyCost')
        require_fields(facts['starCost'], ('current', 'costsX'), 'card.facts.starCost')
        normalized['facts']['dynamicVars'] = dynamic_vars(facts['dynamicVars'], 'card.facts.dynamicVars')
        deck.append(normalized)
    result['deck'] = sorted(deck, key=serialized)
    result['relics'] = sorted(without_presentation(state['relics']), key=serialized)
    if 'relicDetails' in state:
        if not isinstance(state['relicDetails'], list):
            raise ValueError('relicDetailsはlistである必要がある')
        details = []
        for relic in state['relicDetails']:
            require_fields(relic, RELIC_FIELDS, 'relicDetails')
            normalized = {key: without_presentation(relic[key]) for key in RELIC_FIELDS}
            normalized['dynamicVars'] = dynamic_vars(relic['dynamicVars'], 'relicDetails.dynamicVars')
            details.append(normalized)
        if Counter(detail['id'] for detail in details) != Counter(result['relics']):
            raise ValueError('relicDetailsとrelicsのID・個数が一致しない')
        result['relicDetails'] = sorted(details, key=serialized)
    result['potions'] = without_presentation(state['potions'])
    if isinstance(result['potions'], dict) and 'slots' in result['potions']:
        slots = result['potions']['slots']
        indices = [slot['index'] for slot in slots]
        if len(indices) != len(set(indices)):
            raise ValueError('ポーションのスロット番号が重複')
        result['potions']['slots'] = sorted(slots, key=lambda slot: slot['index'])
    return result


def option(candidate):
    index = candidate['option_index']
    if type(index) is not int:
        raise ValueError('イベント候補の公開番号が整数ではない')
    return candidate.get('key'), candidate.get('relic'), index


def event_path(record):
    path, candidates, continuations = [], [], []
    for position, step in enumerate(record['trace']):
        if step['phase'] != 'event' or not step['candidates']:
            continue
        offered = step['candidates']
        selected = [candidate for candidate in offered if candidate['action_id'] == step['response']['action_id']]
        if len(selected) != 1:
            raise ValueError('選択行動をイベントの公開候補へ一意に対応できない')
        chosen = option(selected[0])
        # 実ゲームの終了ページを閉じるIsProceed境界だけを別記録する。
        if len(offered) == 1 and chosen[0] == 'PROCEED' and chosen[1] is None:
            continuations.append({'traceIndex': position, 'option': chosen})
            continue
        path.append(chosen)
        candidates.append(sorted((option(candidate) for candidate in offered), key=serialized))
    return tuple(path), candidates, continuations


def event_identity(event):
    return (event.get('id') or event['name']) if isinstance(event, dict) else event


def load_cases(root):
    root = Path(root).resolve()
    if not root.is_dir():
        raise ValueError('記録ディレクトリがない: ' + str(root))
    records, gaps, failures = [], [], []
    aliases, by_path = {}, {}
    for path in sorted(root.rglob('case.json')):
        try:
            data = path.read_bytes()
            record = json.loads(data)
            record['_source'] = str(path)
            record['_sha256'] = hashlib.sha256(data).hexdigest()
            record['_identity'] = event_identity(record['event'])
            if isinstance(record['event'], dict):
                aliases[record['event']['name']] = record['_identity']
            records.append(record)
            by_path[path.resolve()] = record
        except (OSError, ValueError, KeyError) as error:
            failures.append({'source': str(path), 'error': str(error)})
    summary = root / 'summary.json'
    if summary.is_file():
        try:
            for row in json.loads(summary.read_text())['cases']:
                if not row.get('case'):
                    gap = dict(row)
                    gap['event'] = aliases.get(event_identity(row['event']), event_identity(row['event']))
                    gaps.append(gap)
                    continue
                case_path = (root / row['case'] / 'case.json').resolve()
                if not case_path.is_relative_to(root):
                    raise ValueError('summaryのcaseが記録ディレクトリ外を参照: ' + row['case'])
                record = by_path.get(case_path)
                if record is None:
                    failures.append({'source': str(summary), 'case': row['case'],
                                     'error': 'summaryの参照先case.jsonが存在しないか読めない'})
                elif (record['status'] != row['status']
                      or record['_identity'] != aliases.get(event_identity(row['event']), event_identity(row['event']))):
                    failures.append({'source': str(summary), 'case': row['case'],
                                     'error': 'summaryとcase.jsonのイベントまたは状態が一致しない'})
        except (OSError, ValueError, KeyError) as error:
            failures.append({'source': str(summary), 'error': str(error)})
    return records, gaps, failures


def differing_fields(learn, native):
    return {key: {'learn': learn.get(key), 'native': native.get(key)}
            for key in sorted(set(learn) | set(native)) if learn.get(key) != native.get(key)}


def multiset_delta(before, after):
    before, after = Counter(map(serialized, before)), Counter(map(serialized, after))
    return {'removed': [json.loads(value) for value in sorted((before - after).elements())],
            'added': [json.loads(value) for value in sorted((after - before).elements())]}


def effect(before, after):
    return {'resources': {key: after[key] - before[key] for key in ('hp', 'maxHp', 'gold')},
            'deck': multiset_delta(before['deck'], after['deck']),
            'relics': multiset_delta(before['relics'], after['relics']),
            'relicDetails': {'compared': 'relicDetails' in before and 'relicDetails' in after,
                             'before': before.get('relicDetails'), 'after': after.get('relicDetails')},
            'potions': {'before': before['potions'], 'after': after['potions']},
            'transition': {'phase': after['phase'], 'terminal': after['terminal'],
                           'act': after['act'], 'floor': after['floor']}}


def record_reference(record):
    return {'source': record['_source'], 'sha256': record['_sha256'], 'status': record['status'],
            'error': record.get('error'), 'errorType': record.get('errorType')}


def compare_records(learn, native):
    path, learn_candidates, learn_continuations = event_path(learn)
    native_path, native_candidates, native_continuations = event_path(native)
    assert path == native_path
    result = {'event': learn['_identity'], 'path': path,
              'learn': record_reference(learn), 'native': record_reference(native),
              'semanticEffectVerified': False, 'differences': {}}
    if learn_continuations != native_continuations:
        result['boundaryShapeDifferences'] = {'learn': learn_continuations, 'native': native_continuations,
            'classification': 'single_public_PROCEED_without_relic; effects_still_compared'}
    if learn_candidates != native_candidates:
        result['differences']['eventCandidates'] = {'learn': learn_candidates, 'native': native_candidates}
    if learn.get('initialCondition') != native.get('initialCondition'):
        result['differences']['declaredInitialCondition'] = {
            'learn': learn.get('initialCondition'), 'native': native.get('initialCondition')}
    for backend, record in [('learn', learn), ('native', native)]:
        if record.get('fixture') is not True or record.get('expertData') is not False:
            result['differences'][backend + 'FixtureDeclaration'] = {
                'fixture': record.get('fixture'), 'expertData': record.get('expertData')}
    normalized = {}
    missing_fields = False
    for backend, record in [('learn', learn), ('native', native)]:
        normalized[backend] = {}
        for moment in ('before', 'after'):
            try:
                normalized[backend][moment] = canonical_state(record[moment])
                if 'relicDetails' not in record[moment]:
                    missing_fields = True
                    result['differences'][backend + moment.title() + 'RelicDetailsMissing'] = '元caseにrelicDetailsがなく、カウンター・使用状態・動的値を未比較'
            except (KeyError, TypeError, ValueError) as error:
                missing_fields = True
                result['differences'][backend + moment.title() + 'MissingOrInvalid'] = str(error)
    if all('before' in normalized[backend] for backend in normalized):
        before = differing_fields(normalized['learn']['before'], normalized['native']['before'])
        if before:
            result['differences']['initialPublicState'] = before
    complete = all(record['status'] == 'completed' for record in (learn, native))
    if complete and all('after' in normalized[backend] for backend in normalized):
        after = differing_fields(normalized['learn']['after'], normalized['native']['after'])
        if after:
            result['differences']['finalPublicState'] = after
    for backend in normalized:
        if set(normalized[backend]) == {'before', 'after'}:
            result.setdefault('effects', {})[backend] = effect(normalized[backend]['before'], normalized[backend]['after'])
    if not complete:
        result['status'] = 'execution_incomplete'
    elif missing_fields:
        result['status'] = 'public_fields_missing'
    elif 'initialPublicState' in result['differences']:
        result['status'] = 'initial_state_mismatch'
    elif 'declaredInitialCondition' in result['differences']:
        result['status'] = 'initial_condition_mismatch'
    elif result['differences']:
        result['status'] = 'recorded_state_mismatch'
    else:
        result['status'] = 'recorded_fields_match'
    return result


def compare(learn_root, native_root):
    loaded = {backend: load_cases(root) for backend, root in [('learn', learn_root), ('native', native_root)]}
    groups = {backend: defaultdict(list) for backend in loaded}
    invalid = []
    for backend, (records, gaps, failures) in loaded.items():
        for record in records:
            try:
                path, _, _ = event_path(record)
                groups[backend][(record['_identity'], path)].append(record)
            except (KeyError, TypeError, ValueError) as error:
                invalid.append({'backend': backend, **record_reference(record), 'status': 'invalid_event_trace', 'reason': str(error)})
    rows = []
    for event, path in sorted(set(groups['learn']) | set(groups['native']), key=serialized):
        pair = {backend: groups[backend].get((event, path), []) for backend in groups}
        if not all(pair.values()):
            backend = 'learn' if pair['learn'] else 'native'
            rows.append({'event': event, 'path': path, 'status': 'missing_case',
                         'presentBackend': backend, 'presentCases': list(map(record_reference, pair[backend])),
                         'reason': '同じ公開イベント選択列が片側にない。未実行・方策差・ランダム候補差をこの記録だけでは区別しない。',
                         'semanticEffectVerified': False})
        elif any(len(records) != 1 for records in pair.values()):
            rows.append({'event': event, 'path': path, 'status': 'ambiguous_pair',
                         'learn': list(map(record_reference, pair['learn'])),
                         'native': list(map(record_reference, pair['native'])), 'semanticEffectVerified': False})
        else:
            rows.append(compare_records(pair['learn'][0], pair['native'][0]))
    counts = Counter(row['status'] for row in rows + invalid)
    return {'learnRoot': str(Path(learn_root).resolve()), 'nativeRoot': str(Path(native_root).resolve()),
            'counts': dict(sorted(counts.items())), 'cases': rows, 'invalidRecords': invalid,
            'emptyInputs': [backend for backend, data in loaded.items() if not data[0]],
            'coverageGaps': {backend: data[1] for backend, data in loaded.items()},
            'readErrors': {backend: data[2] for backend, data in loaded.items()},
            'semanticEffectVerified': False, 'allBranchesVerified': False, 'winRateImprovementVerified': False,
            'scope': ['開始Act1・floor1の診断fixture。同じ公開選択列と記録された初期状態・後状態の比較。',
                      'カードの物理ID・デッキ表示順・ローカライズ・backend固有行動IDは比較しない。',
                      'カードはID・強化・keywords・付与・affliction・特殊値と、公開された型・コスト・dynamicVars・retain・slyを比較。',
                      'relicDetailsがある場合はID・表示カウンター・stackCount・isMelted・isUsedUp・dynamicVarsも比較。欠落時は未比較と明示。',
                      '同じ終了状態でも内部処理・未記録効果の同値性は未認定。条件付き全分岐とランダム結果は未網羅。',
                      '終盤専用のTheArchitect文脈、自然出現条件、勝率改善は未検証。']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--learn', type=Path, required=True)
    parser.add_argument('--native', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('出力先は新規ファイルを指定')
    report = compare(args.learn, args.native)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as output:
        output.write(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'output': str(args.output), 'counts': report['counts'],
                      'coverageGaps': {key: len(value) for key, value in report['coverageGaps'].items()}}, ensure_ascii=False))
    incomplete = any(row['status'] != 'recorded_fields_match' for row in report['cases'])
    incomplete |= bool(report['emptyInputs']) or bool(report['invalidRecords']) or any(report['coverageGaps'].values()) or any(report['readErrors'].values())
    raise SystemExit(1 if incomplete else 0)


if __name__ == '__main__':
    main()
