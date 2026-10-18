"""The checker: a fresh session of the same model that compares the agent's animation with the target.

It sees pictures only (filmstrips and motion curves), never the IR, the agent's messages or any score, so its
feedback cannot be gamed by optimising a number. Two kinds of check:
  quick  : after every accepted change, a 16-frame filmstrip of target / previous version / new version;
           the reply says better / same / worse and lists the 3 biggest differences.
  review : the whole animation (48-frame filmstrip + motion curves); the checker may zoom once into a stretch
           of up to 1 s to judge timing frame by frame, and ends with REMAINING: yes / no.
"""
import re
import time

from . import pictures
from .prompts import REVIEW_ZOOM_REPLY, quick_prompt, reviewer_prompt

QUICK_CELLS = 16    # frames in a quick check
REVIEW_CELLS = 48   # frames in a full review filmstrip
ZOOM_CELLS = 24     # at most this many frames for the one zoom request
TRIES = 2           # a session that tries a client tool is discarded and asked again; the agent did nothing wrong


class Checker:
    def __init__(self, new_session, task, times, target, out_dir, stats):
        """new_session(): a fresh model session; target: RGB arrays of the target at every frame time."""
        self.new_session, self.task, self.times, self.target = new_session, task, times, target
        self.dir, self.stats = out_dir, stats
        self.quick_idx = pictures.sample(len(times), QUICK_CELLS)

    def quick(self, yours, previous, tag):
        """yours / previous: frames at self.quick_idx (previous may be None). Returns the checker's reply."""
        times = [self.times[i] for i in self.quick_idx]
        rows = [('target', [self.target[i] for i in self.quick_idx])]
        rows += ([('previous', previous)] if previous is not None else []) + [('yours', yours)]
        strips = pictures.filmstrip(rows, times, self.dir / f'{tag}.png', max_cells=QUICK_CELLS)
        reply = self._ask([(quick_prompt(self.task, previous is not None), strips)])
        self.stats['quick_checks'] = self.stats.get('quick_checks', 0) + 1
        (self.dir / f'{tag}.txt').write_text(reply)
        return reply

    def review(self, yours, tag):
        """yours: frames at every time. Returns (notes, remaining) with remaining True / False / None."""
        idx = pictures.sample(len(self.times), REVIEW_CELLS)
        strips = pictures.filmstrip([('target', [self.target[i] for i in idx]), ('yours', [yours[i] for i in idx])],
                                    [self.times[i] for i in idx], self.dir / f'{tag}_strip.png')
        colours = pictures.palette(self.target)
        curves = pictures.motion_curves(self.times, colours, pictures.tracks(self.target, colours),
                                        pictures.tracks(yours, colours), self.dir / f'{tag}_curves.png')

        def zoom_turn(reply):
            zoom = zoom_request(reply)
            if zoom is None:
                return None
            a, b = zoom
            window = [i for i, t in enumerate(self.times) if a - 1e-6 <= t <= b + 1e-6]
            window = window or [min(range(len(self.times)), key=lambda i: abs(self.times[i] - a))]
            window = [window[j] for j in pictures.sample(len(window), ZOOM_CELLS)]
            zoomed = pictures.filmstrip([('target', [self.target[i] for i in window]), ('yours', [yours[i] for i in window])],
                                        [self.times[i] for i in window], self.dir / f'{tag}_zoom.png', max_cells=ZOOM_CELLS)
            self.stats['zooms'] = self.stats.get('zooms', 0) + 1
            return REVIEW_ZOOM_REPLY, zoomed

        reply = self._ask([(reviewer_prompt(self.task, len(strips)), strips + [curves]), zoom_turn])
        (self.dir / f'{tag}.txt').write_text(reply)
        return review_notes(reply)

    def _ask(self, turns):
        """turns: [(prompt, images)] plus optionally f(first_reply) -> (prompt, images) | None for a second turn."""
        start = time.monotonic()
        try:
            for _ in range(TRIES):
                session = self.new_session()
                self.stats.setdefault('checker', getattr(session, 'identity', None))
                try:
                    reply = session.send(*turns[0])
                    follow = turns[1](reply) if len(turns) > 1 else None
                    reply = session.send(*follow) if follow else reply
                    if not _written_tool_call(reply):
                        return reply
                    self.stats['checker_tool_retries'] = self.stats.get('checker_tool_retries', 0) + 1
                except RuntimeError as error:
                    if 'invalidates_trial' not in str(error):
                        raise
                    self.stats['checker_tool_retries'] = self.stats.get('checker_tool_retries', 0) + 1
                finally:
                    _close_quietly(session)
            return '(The checker could not answer this time.)'
        finally:
            self.stats['checker_seconds'] = round(self.stats.get('checker_seconds', 0) + time.monotonic() - start, 1)


def _close_quietly(session):
    """A checker session that is slow to exit must not end the trial; its reply is already in hand."""
    try:
        session.close()
    except Exception:
        pass


def _written_tool_call(reply):
    """Some models write their native tool-call markup (e.g. DeepSeek's DSML) as text instead of an answer."""
    return 'DSML' in reply or bool(re.search(r'invoke name=\\?"', reply))


def zoom_request(reply):
    """The checker's optional {"zoom":[start,end]} request, if the reply is only that."""
    m = re.search(r'\{\s*"zoom"\s*:\s*\[\s*([0-9.]+)\s*,\s*([0-9.]+)\s*\]\s*\}', reply)
    if not m or len(reply.strip()) > len(m.group(0)) + 200:
        return None
    a, b = sorted((float(m.group(1)), float(m.group(2))))
    return a, min(b, a + 1.0)


def review_notes(reply):
    """(notes without the verdict line, True / False / None for REMAINING)."""
    verdicts = re.findall(r'REMAINING:\s*(yes|no)', reply, re.I)
    notes = re.sub(r'.*REMAINING:\s*(yes|no).*', '', reply, flags=re.I).strip()
    return notes[:4000], (verdicts[-1].lower() == 'yes') if verdicts else None
