"""公開画像で確定した報酬・呪いと、新しく開くセル数を比較する基準方策。"""

from agents.mentor.crystal_vision import recognize
from sts2.observation import Unsupported, metadata


def choose(observation):
    board = observation['state']['crystalSphere']
    width, height = board['width'], board['height']
    if (type(width) is not int or type(height) is not int or min(width, height) < 1
            or board['tool'] not in ('Big', 'Small') or type(board['divinationsLeft']) is not int
            or board['divinationsLeft'] <= 0):
        raise Unsupported('Crystal Sphereの公開盤面・道具・残回数が不正')

    def coordinates(cells):
        result = []
        for cell in cells:
            x, y = cell['col'], cell['row']
            if (type(x) is not int or type(y) is not int
                    or not 0 <= x < width or not 0 <= y < height):
                raise Unsupported('Crystal Sphereの公開セル座標が不正')
            result.append((x, y))
        if len(result) != len(set(result)):
            raise Unsupported('Crystal Sphereの公開セル座標が重複')
        return set(result)

    hidden, revealed = coordinates(board['hiddenCells']), coordinates(board['revealedCells'])
    if hidden & revealed or len(hidden | revealed) != width * height:
        raise Unsupported('Crystal Sphereの公開セル状態に欠落・重複がある')
    clicks, tools = [], {}
    for action in observation['actions']:
        data = metadata(action)
        if action['kind'] == 'crystal_sphere_click':
            point = data['col'], data['row']
            if any(type(v) is not int for v in point) or point not in hidden:
                raise Unsupported('Crystal Sphereのクリック候補が未発掘セルではない')
            clicks.append((action, point))
        elif action['kind'] == 'crystal_sphere_tool':
            tool = data['tool']
            if tool not in ('Big', 'Small') or tool == board['tool'] or tool in tools:
                raise Unsupported('Crystal Sphereの道具切替候補が不正')
            tools[tool] = action
        else:
            raise Unsupported('Crystal Sphereに未対応の候補がある: ' + action['kind'])
    if not clicks:
        raise Unsupported('Crystal Sphereの公開クリック候補がない')

    items, vision = recognize(board, revealed)

    # 実ゲームのhover/CellClickedと同じ公開footprint: Bigは周囲8セル＋中心、Smallは中心。
    def footprint(point, tool):
        x, y = point
        radius = 1 if tool == 'Big' else 0
        return {(a, b) for a in range(x - radius, x + radius + 1)
                for b in range(y - radius, y + radius + 1) if (a, b) in hidden}

    def score(point, tool):
        opened = footprint(point, tool)
        active = [item for item in items if item['remaining']]
        bad = sum(item['curse'] and item['remaining'] <= opened for item in active)
        complete = sum(not item['curse'] and item['remaining'] <= opened for item in active)
        progress = sum(len(item['remaining'] & opened) for item in active if not item['curse'])
        return -bad, complete, progress, len(opened)

    tool = board['tool']
    candidates = [(score(point, candidate_tool), candidate_tool, action, point)
                  for candidate_tool in [tool, *tools] for action, point in clicks]
    best, best_tool, chosen, point = min(candidates,
        key=lambda row: (tuple(-v for v in row[0]), row[1] != tool, row[3][1], row[3][0]))
    if best_tool != tool:
        chosen = tools[best_tool]
    return {'action_id': chosen['id']}, {
        'source': 'fixed_public_crystal_templates' if items else 'fixed_public_crystal_coverage',
        'rule': 'avoid_known_curse_completion; complete_reward; advance_reward; new_cells; keep_tool; row,col',
        'currentTool': tool, 'selectedTool': best_tool,
        'maxNewCellsWithCurrentTool': max(len(footprint(p, tool)) for _, p in clicks),
        'selectedScore': list(best), 'itemVisualsUsed': bool(vision['available']), 'vision': vision}
