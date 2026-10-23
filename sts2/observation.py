"""公開観測の読み取り。detail.metadataは合法候補の意味、idは実行時の識別子。"""

class Unsupported(ValueError):
    pass


def entry(value):
    return value.split('.', 1)[-1]


def card_state(item):
    return item['cardDetails']['state'] if 'cardDetails' in item else item['state']


def is_boss(observation):
    graph = observation['state']['status']['map']
    current = graph['current'] if graph else None
    return bool(current and (current == graph.get('boss') or current == graph.get('secondBoss')))


def metadata(action):
    return action['detail']['metadata']
