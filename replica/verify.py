#!/usr/bin/env python3
"""Compile delivered IRs into After Effects and check that AE draws what the preview showed.

For each run folder with final_ir.json: rebuild in AE (serially; AE is one shared instance), render every frame,
and record the mean absolute pixel difference between the AE frames and the preview frames of the same IR
(0-255 scale; small = the preview the agent worked with is faithful to AE). Saves ae/ frames, verify.json and
a target / preview / AE filmstrip.

    python3 -m replica.verify results/*/
"""
import argparse
import json
from pathlib import Path

import numpy as np

from . import pictures
from .ae import compile_ir
from .ir import frame_tag, frame_times
from .run import ROOT


def verify(folder, owned_root):
    folder = Path(folder)
    record = json.loads((folder / 'result.json').read_text())
    pack = ROOT / 'tasks' / record['task']
    times = frame_times(json.loads((pack / 'public/task.json').read_text()))
    ae_frames, seconds = compile_ir(folder / 'final_ir.json', folder / 'ae', times, owned_root)
    preview = [folder / 'final' / f'proxy-{frame_tag(t)}.png' for t in times]
    diffs = [pictures.mean_abs_diff(a, True, p, False) for a, p in zip(ae_frames, preview)]
    idx = pictures.sample(len(times), 16)
    load = lambda paths, pre: [pictures.load_rgb(paths[i], pre) for i in idx]
    ref = [pack / 'public/reference' / f'ref-{frame_tag(t)}.png' for t in times]
    pictures.filmstrip([('target', load(ref, True)), ('preview', load(preview, False)), ('AE', load(ae_frames, True))],
                       [times[i] for i in idx], folder / 'ae_strip.png', max_cells=16)
    out = {'frames': len(times), 'ae_vs_preview_mean_abs_diff': float(np.mean(diffs)),
           'ae_vs_preview_max_frame_diff': float(max(diffs)), 'compile_seconds': round(seconds, 1)}
    (folder / 'verify.json').write_text(json.dumps(out, indent=2) + '\n')
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument('folders', nargs='+', type=Path)
    p.add_argument('--owned-root', type=Path, default=None,
                   help='folder whose AE projects may be replaced (default: the common parent of the run folders)')
    a = p.parse_args()
    owned = (a.owned_root or Path(*Path(a.folders[0]).resolve().parts[:-1])).resolve()
    for folder in a.folders:
        if (folder / 'final_ir.json').exists():
            print(folder.name, verify(folder, owned))


if __name__ == '__main__':
    main()
