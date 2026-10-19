#!/usr/bin/env python3
"""Offline score of a delivered animation against its target. Never shown to the agent or the checker.

Fixed before any run was scored (do not tune it to the results):

    overlap  per frame, the pixels drawn in the target or the result (more than 24 away from white on some
             channel) form the union; a pixel matches when both drew it and their colours are within 60
             (RGB Euclidean). overlap = matched / union, averaged over all frames with a non-empty union.
    mae      mean absolute difference over all pixels and frames, 0-255, both composited on white.

    python3 tools/score.py <task> <final_ir.json> [<final_ir.json> ...]
"""
import copy
import json
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from replica import pictures  # noqa: E402
from replica.ir import frame_tag, frame_times, validate_ir  # noqa: E402
from replica.proxy import Proxy  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DRAWN = 24
SAME_COLOUR = 60


def frame_scores(target, result):
    t, r = target.astype(np.float32), result.astype(np.float32)
    drawn_t = (255 - t).max(2) > DRAWN
    drawn_r = (255 - r).max(2) > DRAWN
    union = drawn_t | drawn_r
    match = drawn_t & drawn_r & (np.sqrt(((t - r) ** 2).sum(2)) <= SAME_COLOUR)
    return (match.sum() / union.sum() if union.any() else None), np.abs(t - r).mean()


def score(proxy, task_id, ir, scratch):
    pack = ROOT / 'tasks' / task_id
    task = json.loads((pack / 'public/task.json').read_text())
    times = frame_times(task)
    target = [pictures.load_rgb(pack / 'public/reference' / f'ref-{frame_tag(t)}.png', True) for t in times]
    data, _ = validate_ir(copy.deepcopy(ir), task)
    files, _ = proxy.render(data, times, scratch)
    pairs = [frame_scores(a, pictures.load_rgb(f, False)) for a, f in zip(target, files)]
    overlaps = [o for o, _ in pairs if o is not None]
    return {'overlap': float(np.mean(overlaps)), 'mae': float(np.mean([m for _, m in pairs]))}


def main():
    task_id, paths = sys.argv[1], sys.argv[2:]
    proxy, tmp = Proxy(), tempfile.TemporaryDirectory(prefix='score-')
    try:
        for i, p in enumerate(paths):
            s = score(proxy, task_id, json.loads(Path(p).read_text()), Path(tmp.name) / str(i))
            print(json.dumps({'ir': p, **{k: round(v, 3) for k, v in s.items()}}))
    finally:
        proxy.close()


if __name__ == '__main__':
    main()
