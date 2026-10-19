#!/usr/bin/env python3
"""Build the self-made `payment` task: a "payment successful" card, 16 shape layers of rounded rects, circles
and a check stroke, animated only through layer transforms. Unlike the other tasks, its reference frames are
preview renders (headless Chrome + lottie-web), not After Effects renders.

    python3 tools/payment_card.py            # writes tasks/payment/
"""
import copy
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from replica import pictures  # noqa: E402
from replica.ir import frame_tag, frame_times, validate_ir  # noqa: E402
from replica.proxy import Proxy  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
W = H = 360
FR, OP = 30, 100

EASE = ({'x': [0.33], 'y': [0]}, {'x': [0.67], 'y': [1]})      # ease in-out
OUT = ({'x': [0.2], 'y': [0]}, {'x': [0.3], 'y': [1]})         # fast start, soft landing


def rgb(hex_):
    return [int(hex_[i:i + 2], 16) / 255 for i in (1, 3, 5)] + [1]


def static(v):
    return {'a': 0, 'k': v}


def keys(pairs, ease=EASE):
    """pairs: [(frame, value)]; value is a list (or a number for opacity/rotation)."""
    out = []
    for i, (t, v) in enumerate(pairs):
        k = {'t': t, 's': v if isinstance(v, list) else [v]}
        if i < len(pairs) - 1:
            n = len(k['s'])
            o, ii = ease
            k['o'] = {'x': o['x'] * n, 'y': o['y'] * n}
            k['i'] = {'x': ii['x'] * n, 'y': ii['y'] * n}
        out.append(k)
    return {'a': 1, 'k': out}


def group(*items):
    return {'ty': 'gr', 'it': list(items) + [{'ty': 'tr', 'p': static([0, 0]), 'a': static([0, 0]),
                                              's': static([100, 100]), 'r': static(0), 'o': static(100)}]}


def rect(cx, cy, w, h, r, color):
    return group({'ty': 'rc', 'd': 1, 'p': static([cx, cy]), 's': static([w, h]), 'r': static(r)},
                 {'ty': 'fl', 'c': static(rgb(color)), 'o': static(100), 'r': 1})


def ellipse(cx, cy, d, color):
    return group({'ty': 'el', 'd': 1, 'p': static([cx, cy]), 's': static([d, d])},
                 {'ty': 'fl', 'c': static(rgb(color)), 'o': static(100), 'r': 1})


def polyline(points, width, color):
    path = {'c': False, 'v': points, 'i': [[0, 0]] * len(points), 'o': [[0, 0]] * len(points)}
    return group({'ty': 'sh', 'ks': static(path)},
                 {'ty': 'st', 'c': static(rgb(color)), 'o': static(100), 'w': static(width), 'lc': 2, 'lj': 2})


def layer(ind, name, anchor, shapes, p=None, s=None, o=None, r=None):
    """Shapes are drawn in layer space; `anchor` is both the anchor point and the resting position."""
    return {'ty': 4, 'ind': ind, 'nm': name, 'ip': 0, 'op': OP, 'st': 0, 'sr': 1,
            'ks': {'a': static(anchor + [0]), 'p': p or static(anchor + [0]), 's': s or static([100, 100, 100]),
                   'r': r or static(0), 'o': o or static(100)},
            'shapes': shapes}


def pop(t0, t1, over=112):
    """Scale 0 -> overshoot -> 100."""
    mid = t0 + round((t1 - t0) * 0.65)
    return keys([(t0, [0, 0, 100]), (mid, [over, over, 100]), (t1, [100, 100, 100])], OUT)


def slide_in(anchor, t0, t1, dx=0, dy=0):
    x, y = anchor
    return (keys([(t0, [x + dx, y + dy, 0]), (t1, [x, y, 0])], OUT), keys([(t0, 0), (t1, 100)], OUT))


def comp():
    L = []
    add = lambda name, anchor, shapes, **kw: L.append(layer(len(L) + 1, name, anchor, shapes, **kw))
    # Lottie draws the first layer on top, so layers are added front to back.
    confetti = [((-70, -52), '#FFB020'), ((64, -60), '#3D7BFF'), ((-84, 6), '#FF5C7A'),
                ((80, 4), '#22C38E'), ((-40, -82), '#3D7BFF'), ((36, -86), '#FF5C7A')]
    for i, ((dx, dy), color) in enumerate(confetti):
        t0 = 22 + i % 3
        add(f'confetti {i + 1}', [180, 104], [ellipse(180, 104, 10 if i < 4 else 7, color)],
            p=keys([(t0, [180, 104, 0]), (t0 + 18, [180 + dx, 104 + dy, 0])], OUT),
            o=keys([(t0, 0), (t0 + 3, 100), (t0 + 14, 100), (t0 + 26, 0)]))
    add('check', [180, 104], [polyline([[162, 105], [175, 118], [199, 92]], 8, '#FFFFFF')],
        s=pop(20, 30, 125), r=keys([(20, -30), (30, 0)], OUT))
    add('badge', [180, 104], [ellipse(180, 104, 72, '#22C38E')], s=pop(12, 24))
    add('button press', [180, 300], [rect(180, 300, 200, 34, 17, '#3D7BFF')],
        s=keys([(56, [0, 0, 100]), (63, [108, 108, 100]), (68, [100, 100, 100]), (82, [100, 100, 100]),
                (86, [93, 93, 100]), (92, [100, 100, 100])], OUT))
    for i, y in enumerate((236, 254, 272)):
        p, o = slide_in([180, y], 42 + 5 * i, 54 + 5 * i, dy=12)
        add(f'row {i + 1}', [180, y], [rect(118, y, 76, 8, 4, '#C9CEDA'), rect(246, y, 52 - 8 * i, 8, 4, '#8A93A6')],
            p=p, o=o)
    add('divider', [180, 218], [rect(180, 218, 216, 2, 1, '#E3E6EE')], s=keys([(36, [0, 100, 100]), (48, [100, 100, 100])], OUT))
    p, o = slide_in([180, 194], 32, 44, dx=-30)
    add('amount', [180, 194], [rect(180, 194, 120, 22, 6, '#1E2433')], p=p, o=o)
    p, o = slide_in([180, 164], 28, 40, dx=30)
    add('title', [180, 164], [rect(180, 164, 150, 12, 6, '#8A93A6')], p=p, o=o)
    add('card', [180, 190], [rect(180, 190, 264, 316, 22, '#F3F5FA')], s=pop(0, 14, 104),
        o=keys([(0, 0), (6, 100)]))
    return {'v': '5.9.0', 'w': W, 'h': H, 'fr': FR, 'ip': 0, 'op': OP, 'ddd': 0, 'assets': [], 'layers': L}


def main():
    answer = comp()
    task = {'w': W, 'h': H, 'fr': FR, 'ip': 0, 'op': OP}
    data, _ = validate_ir(copy.deepcopy(answer), task)
    times = frame_times(task)
    task.update(id='payment', frames=len(times), duration=round(len(times) / FR, 4), background='white')
    target = ROOT / 'tasks' / 'payment'
    if target.exists():
        shutil.rmtree(target)
    (target / 'public/reference').mkdir(parents=True)
    (target / 'hidden').mkdir()
    proxy, tmp = Proxy(), tempfile.TemporaryDirectory(prefix='payment-')
    try:
        files, _ = proxy.render(data, times, Path(tmp.name))
    finally:
        proxy.close()
    digests, frames = {}, []
    for t, f in zip(times, files):
        img = pictures.load_rgb(f, False)
        dst = target / 'public/reference' / f'ref-{frame_tag(t)}.png'
        pictures.Image.fromarray(img).save(dst)
        digests[dst.name] = hashlib.sha256(dst.read_bytes()).hexdigest()
        frames.append(img)
    (target / 'public/task.json').write_text(json.dumps(task, indent=2) + '\n')
    picks = [round(i * (len(times) - 1) / 11) for i in range(12)]
    rows = [(' / '.join(f'{times[i]:.2f}s' for i in picks[r:r + 4]), [frames[i] for i in picks[r:r + 4]]) for r in range(0, 12, 4)]
    pictures.sheet(rows, ['', '', '', ''], target / 'public/overview.png', cell=200)
    (target / 'hidden/answer.json').write_text(json.dumps(answer, separators=(',', ':')))
    (target / 'manifest.json').write_text(json.dumps({'task': task, 'reference_sha256': digests,
        'answer_sha256': hashlib.sha256((target / 'hidden/answer.json').read_bytes()).hexdigest(),
        'source': 'self-made by tools/payment_card.py; references are preview renders (headless Chrome + lottie-web), not After Effects'}, indent=2) + '\n')
    print('payment', W, 'x', H, len(times), 'frames,', len(answer['layers']), 'layers')


if __name__ == '__main__':
    main()
