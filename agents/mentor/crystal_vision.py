"""公開セルの画像を、全ラン共通の図鑑と照合する。裏配置は入力に使わない。"""
import base64
from functools import lru_cache
import gzip

from sts2.observation import Unsupported


CELL = 57
SHAPES = {'gold_small': (1, 1), 'gold_big': (2, 1), 'curse': (2, 2),
          'potion_common': (1, 3), 'potion_uncommon': (1, 3), 'potion_rare': (2, 2),
          'relic': (4, 4), 'card_common': (2, 2), 'card_uncommon': (2, 2), 'card_rare': (2, 2)}


@lru_cache(maxsize=32)
def raster(encoded, width, height):
    try:
        pixels = gzip.decompress(base64.b64decode(encoded, validate=True))
    except (ValueError, OSError, EOFError) as error:
        raise Unsupported('Crystalの公開画像がRGBA gzip/base64ではない') from error
    if len(pixels) != width * height * 4:
        raise Unsupported('Crystalの公開画像サイズとRGBA長が一致しない')
    return pixels


@lru_cache(maxsize=16)
def template_cells(encoded, width, height):
    pixels = raster(encoded, width, height)
    stride = width * 4
    return {(x, y): b''.join(pixels[(y * CELL + py) * stride + x * CELL * 4:
                                    (y * CELL + py) * stride + (x + 1) * CELL * 4]
                            for py in range(CELL))
            for y in range(height // CELL) for x in range(width // CELL)}


def recognize(board, revealed):
    fragments, templates = board.get('visibleFragments'), board.get('visualTemplates')
    if not templates:
        return [], {'available': False, 'reason': 'public_visual_templates_unavailable'}
    if {t['kind'] for t in templates} != set(SHAPES) or len(templates) != len(SHAPES):
        raise Unsupported('Crystalの固定画像テンプレートに欠落・重複がある')
    crops = {}
    for fragment in fragments or []:
        point = fragment['col'], fragment['row']
        if point not in revealed or point in crops or (fragment['width'], fragment['height']) != (CELL, CELL):
            raise Unsupported('Crystalの画像片が公開セル・固定サイズと一致しない')
        crops[point] = raster(fragment['rgbaGzipBase64'], CELL, CELL)
    if set(crops) != revealed:
        raise Unsupported('Crystalの公開セル画像に欠落がある')
    anchors = {point for point, pixels in crops.items() if any(pixels[3::4])}
    hypotheses = {point: {} for point in anchors}
    for template in templates:
        kind = template['kind']
        w, h = SHAPES[kind]
        if (template['widthCells'], template['heightCells'], template['width'], template['height']) != (w, h, w * CELL, h * CELL):
            raise Unsupported('Crystalの固定画像テンプレートの寸法が不正')
        cells = template_cells(template['rgbaGzipBase64'], w * CELL, h * CELL)
        for y in range(board['height'] - h + 1):
            for x in range(board['width'] - w + 1):
                covered = {point for point in crops if x <= point[0] < x + w and y <= point[1] < y + h}
                seeds = covered & anchors
                if not seeds or any(crops[a, b] != cells[a - x, b - y] for a, b in covered):
                    continue
                identity = (x, y, w, h, kind == 'curse')
                for point in seeds:
                    hypotheses[point].setdefault(identity, set()).add(kind)
    certain = {}
    for matches in hypotheses.values():
        if len(matches) == 1:
            identity, kinds = next(iter(matches.items()))
            certain.setdefault(identity, set()).update(kinds)
    # 相反する矩形を同時に正解としない。画像から位置を絞れないものは保留する。
    occupied = {identity: {(x, y) for x in range(identity[0], identity[0] + identity[2])
                           for y in range(identity[1], identity[1] + identity[3])} for identity in certain}
    conflicts = {a for a in occupied for b in occupied if a != b and occupied[a] & occupied[b]}
    items = [{'col': x, 'row': y, 'widthCells': w, 'heightCells': h,
              'curse': bad, 'kinds': sorted(certain[x, y, w, h, bad]),
              'remaining': occupied[x, y, w, h, bad] - revealed}
             for x, y, w, h, bad in sorted(certain) if (x, y, w, h, bad) not in conflicts]
    return items, {'available': True, 'method': 'exact_visible_cell_templates',
                   'opaqueCells': len(anchors),
                   'ambiguousOrUnknownCells': sum(len(matches) != 1 for matches in hypotheses.values()),
                   'conflictingRectangles': len(conflicts),
                   'recognized': [{k: v for k, v in item.items() if k != 'remaining'} |
                                  {'remainingCells': len(item['remaining'])} for item in items]}
