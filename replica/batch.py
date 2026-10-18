#!/usr/bin/env python3
"""Run a set of sessions in parallel and summarise them.

Runs are named <model>-<condition>-<task>-r<n> inside --root. Finished runs (result.json present) are skipped,
so an interrupted batch resumes where it stopped. Invalid runs (client tool use, crashes) are moved aside as
_invalid-<name>-<time> and rerun. Sessions never touch After Effects, so they can run in parallel; the summary
lists process facts only - results are judged by looking at each run's final_strip.png.

    python3 -m replica.batch --root runs/demo --tasks browser trophy x_pop --repeats 3
"""
import argparse
import json
import random
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .models import MODELS
from .proxy import Proxy
from .run import ROOT, run


def summarise(root):
    lines = []
    for result in sorted(Path(root).glob('*/result.json')):
        if result.parent.name.startswith('_'):
            continue
        r = json.loads(result.read_text())
        s = r['stats']
        acts = ' '.join(f'{k}:{v}' for k, v in sorted(s['actions'].items()))
        lines.append(f"{result.parent.name:40s} valid={r['valid']!s:5s} ended={r['ended']:8s} actions={r['actions_used']:2d} "
                     f"[{acts}] invalid={s['invalid_actions']} quick={s.get('quick_checks', 0)} reviews={s.get('reviews', 0)}")
    text = '\n'.join(lines)
    (Path(root) / 'summary.txt').write_text(text + '\n')
    return text


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--models', nargs='+', default=['dsflash'], choices=list(MODELS))
    p.add_argument('--conditions', nargs='+', default=['loop'], choices=['loop', 'oneshot'])
    p.add_argument('--tasks', nargs='+', default=sorted(d.name for d in (ROOT / 'tasks').iterdir() if d.is_dir()))
    p.add_argument('--repeats', type=int, default=1)
    p.add_argument('--steps', type=int, default=24)
    p.add_argument('--minutes', type=float, default=25)
    p.add_argument('--workers', type=int, default=1, help='parallel sessions (each also starts checker sessions)')
    a = p.parse_args()
    jobs = [(m, c, t, r) for m in a.models for c in a.conditions for t in a.tasks for r in range(1, a.repeats + 1)]
    random.Random(20261016).shuffle(jobs)
    a.root.mkdir(parents=True, exist_ok=True)
    proxy, lock, done = Proxy(), threading.Lock(), [0]

    def work(job):
        model, condition, task, rep = job
        name = f'{model}-{condition}-{task}-r{rep}'
        folder = a.root / name
        if (folder / 'result.json').exists() and json.loads((folder / 'result.json').read_text()).get('valid'):
            return
        if folder.exists():
            shutil.move(str(folder), str(a.root / f'_invalid-{name}-{int(time.time())}'))
        r = run(model, condition, ROOT / 'tasks' / task, folder, proxy, a.steps, a.minutes)
        with lock:
            done[0] += 1
            print(f"[{done[0]}/{len(jobs)}] {name}: valid={r['valid']} ended={r['ended']} actions={r['actions_used']}", flush=True)

    try:
        with ThreadPoolExecutor(max_workers=a.workers) as pool:
            list(pool.map(work, jobs))
    finally:
        proxy.close()
    print(summarise(a.root))


if __name__ == '__main__':
    main()
