"""既存の公開状態→価値入力の投影。モデル・ゲームの型をimportしない。"""
import json

def stable(value):
    if isinstance(value, dict):
        return {k: stable(v) for k, v in sorted(value.items()) if k not in {'instance', 'identityScope', 'index'}}
    if isinstance(value, list):
        return [stable(v) for v in value]
    return value

def canonical(value):
    return json.dumps(stable(value), ensure_ascii=False, sort_keys=True, separators=(',', ':'))

def project(observation):
    state = observation['state']
    status = state['status']
    deck = [stable(c['cardDetails']['state']) for c in status['deckCards']]
    return {
        'schema': 'public-run-afterstate-1',
        'phase': state['phase'],
        'run': {k: status[k] for k in ['act', 'floor', 'hp', 'maxHp', 'gold', 'maxEnergy', 'ascension']},
        'deck': sorted(deck, key=canonical),
        'relics': sorted(stable(status['relicDetails']), key=lambda r: r['id']),
        'potion_belt': stable(status['potionBelt']),
        'map': stable(status.get('map')),
    }
