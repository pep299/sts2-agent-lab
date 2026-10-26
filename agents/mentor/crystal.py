"""公開済みのセルだけで、次に開くセル数を比較する固定基準方策。"""

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

    # 実ゲームのhover/CellClickedと同じ公開footprint: Bigは周囲8セル＋中心、Smallは中心。
    def gain(point, tool):
        x, y = point
        radius = 1 if tool == 'Big' else 0
        return sum((a, b) in hidden for a in range(x - radius, x + radius + 1)
                   for b in range(y - radius, y + radius + 1))

    tool = board['tool']
    chosen, point = min(clicks, key=lambda row: (-gain(row[1], tool), row[1][1], row[1][0]))
    count = gain(point, tool)
    if tool == 'Small' and 'Big' in tools and max(gain(p, 'Big') for _, p in clicks) > count:
        chosen = tools['Big']
    return {'action_id': chosen['id']}, {'source': 'fixed_public_crystal_coverage',
        'rule': 'maximize_new_hidden_cells; tie=row,col; keep_tool_when_equal',
        'currentTool': tool, 'maxNewCellsWithCurrentTool': count,
        'itemVisualsUsed': False}
