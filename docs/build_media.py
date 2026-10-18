#!/usr/bin/env python3
"""Render the README media from results/: per-run filmstrips, target-vs-result GIFs and the iteration strip.

    python3 docs/build_media.py
"""
import copy
import json
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from replica import pictures  # noqa: E402
from replica.ir import frame_tag, frame_times, validate_ir  # noqa: E402
from replica.proxy import Proxy  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
MEDIA = ROOT / 'docs' / 'media'
ITERATIONS = ('browser', [1, 4, 8, 15])   # versions shown in the iteration strip
GIF_FRAMES = 90


def task_frames(task):
    pack = ROOT / 'tasks' / task
    info = json.loads((pack / 'public/task.json').read_text())
    times = frame_times(info)
    return info, times, [pictures.load_rgb(pack / 'public/reference' / f'ref-{frame_tag(t)}.png', True) for t in times]


def render(proxy, ir, info, times, out):
    data, _ = validate_ir(copy.deepcopy(ir), info)
    files, _ = proxy.render(data, times, out)
    return [pictures.load_rgb(f, False) for f in files]


def labelled(frames_by_row, labels, cell=200, pad=10, label_h=26):
    """One GIF frame: columns of animations, each with a caption above. frames_by_row: [array per column]."""
    font = pictures._font(15)
    w = pad + len(frames_by_row) * (cell + pad)
    image = Image.new('RGB', (w, label_h + cell + pad), (250, 250, 252))
    draw = ImageDraw.Draw(image)
    for c, (frame, label) in enumerate(zip(frames_by_row, labels)):
        x = pad + c * (cell + pad)
        draw.text((x + 2, 5), label, fill=(40, 40, 48), font=font)
        p = Image.fromarray(frame).resize((cell, cell), Image.LANCZOS)
        image.paste(p, (x, label_h))
        draw.rectangle([x - 1, label_h - 1, x + cell, label_h + cell], outline=(214, 216, 224))
    return image


def save_gif(frames, fps, out):
    step = max(1, int(np.ceil(len(frames) / GIF_FRAMES)))
    frames = frames[::step]
    hold = [frames[-1]] * max(1, int(fps / step))   # rest on the last frame for about a second
    frames = frames + hold
    frames[0].save(out, save_all=True, append_images=frames[1:], duration=int(1000 * step / fps), loop=0, optimize=True)


def main():
    MEDIA.mkdir(parents=True, exist_ok=True)
    tmp = tempfile.TemporaryDirectory(prefix='motion-replica-media-')
    scratch = Path(tmp.name)
    proxy = Proxy()
    try:
        for run in sorted(p for p in (ROOT / 'results').iterdir() if p.is_dir()):
            info, times, target = task_frames(run.name)
            final = render(proxy, json.loads((run / 'final_ir.json').read_text()), info, times, scratch / run.name)
            idx = pictures.sample(len(times), 16)
            pictures.filmstrip([('target', [target[i] for i in idx]), ('result', [final[i] for i in idx])],
                               [times[i] for i in idx], run / 'final_strip.png', max_cells=16)
            gif = [labelled([t, f], ['target (After Effects)', 'agent result']) for t, f in zip(target, final)]
            save_gif(gif, info['fr'], MEDIA / f'{run.name}.gif')
            print('rendered', run.name)
        task, versions = ITERATIONS
        info, times, target = task_frames(task)
        idx = pictures.sample(len(times), 8)
        rows = [('target', [target[i] for i in idx])]
        for v in versions:
            ir = json.loads((ROOT / 'results' / task / 'versions' / f'ir_v{v:03d}.json').read_text())
            frames = render(proxy, ir, info, [times[i] for i in idx], scratch / f'{task}_v{v}')
            rows.append((f'v{v}', frames))
        pictures.filmstrip(rows, [times[i] for i in idx], MEDIA / f'{task}_iterations.png', max_cells=8)
        print('rendered iteration strip')
    finally:
        proxy.close()
        tmp.cleanup()


if __name__ == '__main__':
    main()
