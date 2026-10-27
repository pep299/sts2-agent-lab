"""開いたセルの内容と、新しく開くセル数を使う基準方策。"""

from sts2.observation import Unsupported, metadata


SHAPES = {'gold': ((1, 1), (2, 1)), 'potion': ((1, 3), (2, 2)),
          'card_reward': ((2, 2),), 'relic': ((4, 4),), 'curse': ((2, 2),)}


def infer_items(board, revealed):
    contents = {(c['col'], c['row']): c['content'] for c in board['revealedCells']}
    if any(content not in {'empty', *SHAPES} for content in contents.values()):
        raise Unsupported('Crystal Sphereの公開セル内容が不明')
    hypotheses = {point: set() for point, kind in contents.items() if kind != 'empty'}
    for kind, shapes in SHAPES.items():
        for w, h in shapes:
            for y in range(board['height'] - h + 1):
                for x in range(board['width'] - w + 1):
                    covered = {p for p in revealed if x <= p[0] < x + w and y <= p[1] < y + h}
                    if not covered or any(contents[p] != kind for p in covered):
                        continue
                    for point in covered:
                        hypotheses[point].add((x, y, w, h, kind))
    certain = {next(iter(matches)) for matches in hypotheses.values() if len(matches) == 1}
    occupied = {item: {(x, y) for x in range(item[0], item[0] + item[2])
                       for y in range(item[1], item[1] + item[3])} for item in certain}
    conflicts = {a for a in certain for b in certain if a != b and occupied[a] & occupied[b]}
    items = [{'col': x, 'row': y, 'widthCells': w, 'heightCells': h, 'kind': kind,
              'curse': kind == 'curse', 'remaining': occupied[x, y, w, h, kind] - revealed}
             for x, y, w, h, kind in sorted(certain - conflicts)]
    return items, {'method': 'public_cell_contents_and_known_shapes',
        'ambiguousOrUnknownCells': sum(len(matches) != 1 for matches in hypotheses.values()),
        'inferredItems': [{k: v for k, v in item.items() if k != 'remaining'} |
                          {'remainingCells': len(item['remaining'])} for item in items]}


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

    items, inference = infer_items(board, revealed)

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
        'source': 'fixed_public_crystal_contents' if items else 'fixed_public_crystal_coverage',
        'rule': 'avoid_known_curse_completion; complete_reward; advance_reward; new_cells; keep_tool; row,col',
        'currentTool': tool, 'selectedTool': best_tool,
        'maxNewCellsWithCurrentTool': max(len(footprint(p, tool)) for _, p in clicks),
        'selectedScore': list(best), 'inference': inference}
