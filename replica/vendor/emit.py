#!/usr/bin/env python3
"""Emit one guarded AE reconstruction from an explicit, immutable input JSON."""
import argparse
import json
from pathlib import Path

def main():
    p = argparse.ArgumentParser()
    p.add_argument('comp', type=Path)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--snap-dir', type=Path, required=True)
    p.add_argument('--times', nargs='+', type=float, default=[0, 3.3, 7.7])
    p.add_argument('--owned-root', type=Path, required=True)
    a = p.parse_args()
    data = json.loads(a.comp.read_text())
    if any(t < 0 or t >= data['op']/data['fr'] for t in a.times):
        p.error('Snapshot outside composition duration')
    a.snap_dir.mkdir(parents=True, exist_ok=True)
    config = {'output': str(a.snap_dir.resolve()), 'ownedRoot': str(a.owned_root.resolve()), 'times': a.times}
    script = 'var IR = '+json.dumps(data,ensure_ascii=True)+';\nvar CONFIG = '+json.dumps(config)+';\n'
    script += Path(__file__).with_name('builder.jsx').read_text()
    a.out.write_text(script)
    print(a.out)

if __name__ == '__main__':
    main()
