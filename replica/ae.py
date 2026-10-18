"""After Effects delivery: rebuild an IR with the verified builder, save the project and render frames.

All AE work goes through vendor/ae_run.sh, which allows a single AE instance and serialises scripts.
"""
import json
import subprocess
import sys
import time
from pathlib import Path

from .ir import frame_tag
from .vendor.frame_ready import wait_for_frames

VENDOR = Path(__file__).resolve().parent / 'vendor'
DISPATCH = VENDOR / 'ae_run.sh'


def dispatch(script, timeout=600):
    """Run one .jsx through the dispatcher. Returns (ok, error_text, seconds)."""
    start = time.monotonic()
    done = subprocess.run(['bash', str(DISPATCH), str(script)], capture_output=True, text=True, timeout=timeout + 60,
                          env={'AE_TIMEOUT': str(timeout), 'PATH': '/usr/bin:/bin:/usr/sbin:/sbin'})
    lines = [l for l in done.stdout.splitlines() if l.startswith('{')]
    if not lines:
        raise RuntimeError(f'AE dispatcher gave no result (exit {done.returncode}): {done.stdout[-300:]} {done.stderr[-300:]}')
    result = json.loads(lines[-1])
    return result['status'] == 'PASS', result.get('error'), time.monotonic() - start


def compile_ir(ir_path, out_dir, times, owned_root):
    """Rebuild in AE and render `times`. Returns (frame_paths, seconds). Raises with AE's message on failure.
    owned_root: the only folder whose projects the builder may replace."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    script = out_dir / 'rebuild.jsx'
    subprocess.run([sys.executable, str(VENDOR / 'emit.py'), str(ir_path), '--out', str(script), '--snap-dir', str(out_dir),
                    '--owned-root', str(owned_root), '--times', *[str(t) for t in times]], check=True, capture_output=True)
    ok, error, seconds = dispatch(script)
    if not ok:
        raise RuntimeError('AE rebuild failed: ' + str(error))
    frames = [out_dir / f'ae-{frame_tag(t)}.png' for t in times]
    wait_for_frames(frames, timeout=60)
    return frames, seconds


def release(owned_root):
    """Leave AE on an empty project, closing the current one only if it is clean and saved inside owned_root."""
    owned = str(Path(owned_root).resolve()) + '/'
    script = Path(owned_root) / f'release_{int(time.time())}.jsx'
    script.write_text(f'''
var p = app.project;
if (p && p.numItems > 0) {{
  if (!p.file || p.file.fsName.indexOf({json.dumps(owned)}) !== 0) throw new Error('Refusing to replace a user project or unsaved work');
  p.close(CloseOptions.DO_NOT_SAVE_CHANGES);
  app.newProject();
}}''')
    ok, error, _ = dispatch(script, timeout=60)
    script.unlink()
    if not ok:
        raise RuntimeError('release failed: ' + str(error))
