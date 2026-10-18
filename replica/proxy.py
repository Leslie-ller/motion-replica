"""Millisecond Lottie preview: one headless Chrome for the whole run, driven over stdin/stdout."""
import json
import queue
import subprocess
import threading
from pathlib import Path

SERVER = Path(__file__).resolve().parent / 'vendor' / 'preview_server.mjs'


class Proxy:
    def __init__(self):
        self.proc = subprocess.Popen(['node', str(SERVER)], cwd=SERVER.parent, stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        self.lines = queue.Queue()
        threading.Thread(target=lambda: [self.lines.put(l) for l in self.proc.stdout], daemon=True).start()
        hello = json.loads(self.lines.get(timeout=60))
        if not hello.get('ready'):
            raise RuntimeError('preview server failed to start')
        self.lottie = hello['lottie']
        self.counter = 0
        self.lock = threading.Lock()

    def render(self, comp, times, out, prefix='proxy'):
        """Render a normalized comp at `times` into PNGs in `out`. Returns (paths, milliseconds)."""
        with self.lock:
            self.counter += 1
            self.proc.stdin.write(json.dumps({'id': self.counter, 'comp': comp, 'times': list(times),
                                              'out': str(out), 'prefix': prefix}) + '\n')
            self.proc.stdin.flush()
            reply = json.loads(self.lines.get(timeout=120))
        if reply.get('error'):
            raise ValueError('preview failed: ' + reply['error'])
        if reply.get('errors'):
            raise ValueError('preview page errors: ' + '; '.join(reply['errors'])[:500])
        return [Path(f) for f in reply['files']], reply['ms']

    def close(self):
        try:
            self.proc.stdin.close()
            self.proc.wait(timeout=10)
        except Exception:
            self.proc.kill()
