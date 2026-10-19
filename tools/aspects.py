#!/usr/bin/env python3
"""Loop vs one-shot on six aspects of the delivered animation, for the runs in results/comparison/irs/
(same model and code, browser / trophy / x_pop, three runs each). Writes results/comparison/aspects.json.
Offline only: never shown to the agent or the checker.

Aspects, per run (colours = the target's main element colours, as in the checker's motion curves):
    onset_err_s       per colour, |first visible time in target - in result|, mean; a missing colour counts the clip length
    pos_err           centre distance in canvas units over frames where both show the colour
    area_err          summed |area difference| / summed target area
    colours_present   share of target colours that appear in the result at all
    visibility_agree  share of (colour, frame) pairs where both agree on visible / not visible
    overlap_tol5      drawn pixels of each side that lie within 5 px of the other side's drawn pixels

    python3 tools/aspects.py
"""
import copy
import json
import sys
import tempfile
from pathlib import Path

import numpy as np
from scipy.ndimage import binary_dilation

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from replica import pictures  # noqa: E402
from replica.ir import frame_tag, frame_times, validate_ir  # noqa: E402
from replica.proxy import Proxy  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
IRS = ROOT / 'results' / 'comparison' / 'irs'
TOLERANCE = np.ones((11, 11), bool)   # 5 px each way


def drawn(f):
    return (255 - f.astype(np.float32)).max(2) > 24


def aspects(target, result, times, colours):
    tt, tr = pictures.tracks(target, colours), pictures.tracks(result, colours)
    vis_t, vis_r = ~np.isnan(tt[..., 0]), ~np.isnan(tr[..., 0])
    shown = [k for k in range(len(colours)) if vis_t[k].any()]
    onset = [abs(times[np.argmax(vis_t[k])] - times[np.argmax(vis_r[k])]) if vis_r[k].any() else times[-1] for k in shown]
    both = vis_t & vis_r
    pos = np.hypot(tt[..., 1] - tr[..., 1], tt[..., 2] - tr[..., 2])[both].mean() if both.any() else 1.0
    area = np.abs(np.nan_to_num(tt[..., 0]) - np.nan_to_num(tr[..., 0])).sum() / np.nansum(tt[..., 0])
    overlap = []
    for a, b in zip(target, result):
        da, db = drawn(a), drawn(b)
        if (da | db).any():
            overlap.append(((da & binary_dilation(db, TOLERANCE)).sum() + (db & binary_dilation(da, TOLERANCE)).sum())
                           / (da.sum() + db.sum()))
    return {'onset_err_s': np.mean(onset), 'pos_err': pos, 'area_err': area,
            'colours_present': np.mean([vis_r[k].any() for k in shown]),
            'visibility_agree': (vis_t == vis_r).mean(), 'overlap_tol5': np.mean(overlap)}


def main():
    rows = []
    proxy, tmp = Proxy(), tempfile.TemporaryDirectory(prefix='aspects-')
    try:
        for task in ('browser', 'trophy', 'x_pop'):
            pack = ROOT / 'tasks' / task
            info = json.loads((pack / 'public/task.json').read_text())
            times = np.array(frame_times(info))
            target = [pictures.load_rgb(pack / 'public/reference' / f'ref-{frame_tag(t)}.png', True) for t in times]
            colours = pictures.palette(target)
            for condition in ('oneshot', 'loop'):
                for r in (1, 2, 3):
                    row = {'task': task, 'condition': condition, 'run': r}
                    f = IRS / f'{condition}-{task}-r{r}.json'
                    if not f.exists():
                        rows.append(dict(row, valid=False))
                        continue
                    data, _ = validate_ir(copy.deepcopy(json.loads(f.read_text())), info)
                    files, _ = proxy.render(data, list(times), Path(tmp.name) / f.stem)
                    result = [pictures.load_rgb(x, False) for x in files]
                    rows.append(dict(row, valid=True, **{k: round(float(v), 3) for k, v in
                                                         aspects(target, result, times, colours).items()}))
                    print(json.dumps(rows[-1]))
    finally:
        proxy.close()
    (ROOT / 'results' / 'comparison' / 'aspects.json').write_text(json.dumps(rows, indent=1) + '\n')


if __name__ == '__main__':
    main()
