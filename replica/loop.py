"""One reproduction session per (task, condition): executes the agent's JSON actions and keeps the state.

Conditions
  loop    : generate - check - fix. Actions set_ir / patch_ir / get_ir / preview / review / finish.
            Every accepted change gets an automatic quick check from the checker (not counted as an action);
            from action AUTO_REVIEW_AT on, a full review replaces it if none was done yet, and once more near the
            end. Nothing in the loop sees a score. The last accepted version is delivered.
  oneshot : baseline. One submission, same opening pictures, no feedback.
"""
import copy
import json
import time
from pathlib import Path

from . import pictures
from .checker import Checker
from .ir import apply_patch, frame_tag, frame_times, validate_ir

MAX_PREVIEW = 6
AUTO_REVIEW_AT = 12  # from this action on, an accepted change gets a full review if none was done yet ...
REMIND_LEFT = 4      # ... and again with this many actions left; finish is answered with one reminder before that
ACTIONS = {'loop': {'set_ir', 'patch_ir', 'get_ir', 'preview', 'review', 'finish'}, 'oneshot': {'submit'}}


class Session:
    def __init__(self, pack, out_dir, condition, proxy, new_checker_session=None, steps=24):
        self.pack, self.dir = Path(pack), Path(out_dir)
        self.dir.mkdir(parents=True, exist_ok=False)
        self.condition, self.proxy = condition, proxy
        self.task = json.loads((self.pack / 'public/task.json').read_text())
        self.times = frame_times(self.task)
        self.ref = {t: self.pack / 'public/reference' / f'ref-{frame_tag(t)}.png' for t in self.times}
        self.target = [pictures.load_rgb(self.ref[t], True) for t in self.times]
        self.steps = 1 if condition == 'oneshot' else steps
        self.ir = None          # last accepted IR (what preview, review and delivery use)
        self.draft = None       # last submitted IR, accepted or not (what patch_ir edits)
        self.version = 0
        self.calls = 0
        self.reviews = 0
        self.remaining = None   # did the last review report differences? (None = no review yet)
        self.reminded = False
        self.shown = None       # quick-check frames of the previous accepted version
        self.stats = {'actions': {}, 'invalid_actions': 0, 'tool_seconds': 0.0, 'previews': 0}
        self.checker = Checker(new_checker_session, self.task, self.times, self.target, self.dir, self.stats) \
            if condition == 'loop' else None

    # ---- dispatch ------------------------------------------------------------------------------
    def step(self, action):
        """Returns (text, images, finished). ValueError messages go back to the agent as errors."""
        if not isinstance(action, dict) or not isinstance(action.get('action'), str):
            raise ValueError('reply with one JSON object containing "action"')
        name = action['action']
        self.calls += 1
        self.stats['actions'][name] = self.stats['actions'].get(name, 0) + 1
        if name not in ACTIONS[self.condition]:
            raise ValueError(f'unknown action "{name}"; allowed: {", ".join(sorted(ACTIONS[self.condition]))}')
        start = time.monotonic()
        try:
            return getattr(self, '_do_' + name)(action)
        finally:
            self.stats['tool_seconds'] += time.monotonic() - start

    def _do_set_ir(self, action):
        if 'ir' not in action:
            raise ValueError('"ir" is required')
        return (*self._accept(copy.deepcopy(action['ir'])), False)

    def _do_submit(self, action):
        text, images, _ = self._do_set_ir(action)
        return text, images, True

    def _do_patch_ir(self, action):
        if self.draft is None:
            raise ValueError('no IR yet; start with set_ir')
        return (*self._accept(apply_patch(self.draft, action.get('ops'))), False)

    def _do_get_ir(self, action):
        if self.draft is None:
            raise ValueError('no IR yet; start with set_ir')
        state = 'accepted' if self.draft == self.ir else 'draft (not accepted)'
        return f'Current {state} IR:\n' + json.dumps(self.draft, separators=(',', ':')), [], False

    def _do_preview(self, action):
        self._need_ir()
        times = self._snap(action.get('times'))
        self.stats['previews'] += 1
        tag = f'preview_{self.stats["previews"]:03d}'
        yours = self._frames(times, tag)
        rows = []
        for t, y in zip(times, yours):
            target = self.target[self.times.index(t)]
            rows.append((f't={t:.3f}s', [target, y, pictures.heatmap(target, y)]))
        out = pictures.sheet(rows, ['target', 'yours', 'difference'], self.dir / f'{tag}.png')
        return 'Preview (target | yours | difference heat map: black = same, bright = different).', [out], False

    def _do_review(self, action):
        self._need_ir()
        return self._review(), [], False

    def _do_finish(self, action):
        left = self.steps - self.calls
        if self.condition == 'loop' and not self.reminded and left >= REMIND_LEFT and self.remaining is not False:
            self.reminded = True
            self.stats['finish_reminders'] = 1
            why = ('you have not asked for a review of your current version' if self.remaining is None
                   else 'your last review still listed clear differences')
            return (f'Not finished yet: {why}, and you have {left} actions left. Fix what remains, or call review; '
                    f'send finish again to deliver your current version as it is.'), [], False
        return 'Finished.', [], True

    # ---- state changes and checks ------------------------------------------------------------------
    def _accept(self, ir):
        self.draft = copy.deepcopy(ir)
        try:
            validate_ir(ir, self.task)  # fills defaults in place; the completed form is stored
        except ValueError as error:
            raise ValueError(f'{error}\nNot accepted; your draft is kept, so you can fix it with patch_ir.'
                             + (f' The last accepted version ({self.version}) is still active.' if self.version else '')) from None
        self.ir = ir
        self.version += 1
        (self.dir / f'ir_v{self.version:03d}.json').write_text(json.dumps(ir, separators=(',', ':')))
        text = f'Accepted as version {self.version}: {len(ir["layers"])} layer(s).'
        if self.condition == 'loop':
            left = self.steps - self.calls
            due = self.calls >= AUTO_REVIEW_AT and (self.reviews == 0 or (self.reviews < 2 and left <= REMIND_LEFT))
            text += '\n' + (self._review(automatic=True) if due else self._quick())
        return text, []

    def _quick(self):
        times = [self.times[i] for i in self.checker.quick_idx]
        yours = self._frames(times, f'quick_{self.version:03d}')
        reply = self.checker.quick(yours, self.shown, f'quick_{self.version:03d}')
        self.shown = yours
        return f'Quick check of version {self.version} by the checker (short filmstrip only):\n' + reply.strip()[:2000]

    def _review(self, automatic=False):
        self.reviews += 1
        tag = f'review_{self.reviews:03d}'
        yours = self._frames(self.times, tag)
        notes, self.remaining = self.checker.review(yours, tag)
        self.shown = [yours[i] for i in self.checker.quick_idx]
        self.stats['reviews'] = self.reviews
        if automatic:
            self.stats['auto_reviews'] = self.stats.get('auto_reviews', 0) + 1
        verdict = {True: 'The checker still sees clear differences.', False: 'The checker sees no clear differences left.',
                   None: 'The checker gave no verdict.'}[self.remaining]
        return (f'{"Automatic full review" if automatic else "Review"} {self.reviews} (the checker compared filmstrips and '
                f'motion curves of the target and your version {self.version}):\n{notes}\n{verdict}')

    # ---- helpers -------------------------------------------------------------------------------
    def _need_ir(self):
        if self.ir is None:
            raise ValueError('no IR yet; start with set_ir')

    def _snap(self, times):
        if not isinstance(times, list) or not times or len(times) > MAX_PREVIEW:
            raise ValueError(f'"times" must list 1-{MAX_PREVIEW} times in seconds')
        result = []
        for t in times:
            if not isinstance(t, (int, float)):
                raise ValueError('times must be numbers (seconds)')
            nearest = min(self.times, key=lambda x: abs(x - t))
            if abs(nearest - t) > 1.5 / self.task['fr']:
                raise ValueError(f'time {t} is outside 0..{self.times[-1]:.3f} s')
            result.append(nearest)
        return result

    def _frames(self, times, folder, ir=None):
        data, _ = validate_ir(copy.deepcopy(ir or self.ir), self.task)
        files, _ = self.proxy.render(data, times, self.dir / folder)
        return [pictures.load_rgb(f, False) for f in files]

    # ---- delivery ------------------------------------------------------------------------------
    def deliver(self):
        """Save the last accepted IR, render every frame and a target / result filmstrip. No score is computed:
        results are judged by looking at them (and the IR can be compiled into AE with verify.py)."""
        if self.ir is None:
            return {'delivered': False}
        (self.dir / 'final_ir.json').write_text(json.dumps(self.ir, separators=(',', ':')))
        data, _ = validate_ir(copy.deepcopy(self.ir), self.task)
        files, _ = self.proxy.render(data, self.times, self.dir / 'final')
        idx = pictures.sample(len(self.times), 16)
        frames = [pictures.load_rgb(files[i], False) for i in idx]
        pictures.filmstrip([('target', [self.target[i] for i in idx]), ('result', frames)],
                           [self.times[i] for i in idx], self.dir / 'final_strip.png', max_cells=16)
        return {'delivered': True, 'version': self.version}
