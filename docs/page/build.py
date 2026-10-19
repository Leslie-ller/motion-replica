#!/usr/bin/env python3
"""Build the project page (docs/page/index.html + sprites/ + img/) from results/ and tasks/.

Sprites are sheets of every frame (10 per row) that the page's synced player draws onto canvases.

    python3 docs/page/build.py
"""
import copy
import json
import math
import sys
import tempfile
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from replica import pictures  # noqa: E402
from replica.ir import frame_tag, frame_times, validate_ir  # noqa: E402
from replica.proxy import Proxy  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
TASKS = [('browser', '浏览器窗口'), ('payment', '支付卡片'), ('x_pop', '叉号弹出')]
PREVIEW_TARGETS = {'payment'}   # self-made task: its reference frames are preview renders, not AE
ITER = ('browser', [1, 4, 8, 15])
CELL_H, COLS = 160, 10
IMAGES = {'checker_quick.webp': 'results/browser/checks/quick_004.png',
          'checker_curves.webp': 'results/browser/checks/review_001_curves.png',
          'preview_vs_ae.webp': 'docs/media/preview_vs_ae.png'}


def sprite(frames, name, step):
    frames = frames[::step]
    h, w = frames[0].shape[:2]
    cw = round(w * CELL_H / h)
    sheet = Image.new('RGB', (cw * COLS, CELL_H * math.ceil(len(frames) / COLS)), 'white')
    for i, f in enumerate(frames):
        sheet.paste(Image.fromarray(f).resize((cw, CELL_H), Image.LANCZOS), ((i % COLS) * cw, (i // COLS) * CELL_H))
    sheet.save(OUT / 'sprites' / name, 'WEBP', quality=80, method=6)
    return cw


def main():
    (OUT / 'sprites').mkdir(exist_ok=True)
    (OUT / 'img').mkdir(exist_ok=True)
    tmp = tempfile.TemporaryDirectory(prefix='motion-replica-page-')
    proxy = Proxy()
    data = {'tasks': [], 'iterations': None}
    try:
        def render(task, ir, times, tag):
            data_ir, _ = validate_ir(copy.deepcopy(ir), task)
            files, _ = proxy.render(data_ir, times, Path(tmp.name) / tag)
            return [pictures.load_rgb(f, False) for f in files]

        for tid, name in TASKS:
            pack = ROOT / 'tasks' / tid
            task = json.loads((pack / 'public/task.json').read_text())
            times = frame_times(task)
            step = 2 if task['fr'] > 40 else 1
            target = [pictures.load_rgb(pack / 'public/reference' / f'ref-{frame_tag(t)}.png', True) for t in times]
            final = render(task, json.loads((ROOT / 'results' / tid / 'final_ir.json').read_text()), times, tid)
            run = json.loads((ROOT / 'results' / tid / 'run.json').read_text())
            cw = sprite(target, f'{tid}-target.webp', step)
            sprite(final, f'{tid}-result.webp', step)
            entry = {'id': tid, 'name': name, 'w': cw, 'h': CELL_H, 'cols': COLS, 'n': len(times[::step]),
                     'fps': task['fr'] / step, 'duration': task['duration'], 'frames': len(times),
                     'target': f'sprites/{tid}-target.webp', 'result': f'sprites/{tid}-result.webp',
                     'actions': run['actions_used'], 'versions': run['versions'], 'ended': run['ended'],
                     'quick': run['stats'].get('quick_checks', 0), 'reviews': run['stats'].get('reviews', 0),
                     'source': '预览' if tid in PREVIEW_TARGETS else 'After Effects'}
            data['tasks'].append(entry)
            if tid == ITER[0]:
                versions = []
                for v in ITER[1]:
                    ir = json.loads((ROOT / 'results' / tid / 'versions' / f'ir_v{v:03d}.json').read_text())
                    sprite(render(task, ir, times, f'{tid}-v{v}'), f'{tid}-v{v}.webp', step)
                    versions.append({'v': v, 'sprite': f'sprites/{tid}-v{v}.webp'})
                data['iterations'] = dict(entry, versions=versions)
            print('sprites', tid)
    finally:
        proxy.close()
        tmp.cleanup()
    for out, src in IMAGES.items():
        Image.open(ROOT / src).convert('RGB').save(OUT / 'img' / out, 'WEBP', quality=85, method=6)
    html = (OUT / 'template.html').read_text().replace('__DATA__', json.dumps(data, ensure_ascii=False))
    (OUT / 'index.html').write_text(html)
    print('wrote', OUT / 'index.html')


if __name__ == '__main__':
    main()
