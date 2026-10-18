#!/usr/bin/env python3
"""End-to-end checks with scripted sessions instead of a model (no client, no AE; needs node + Chrome).

  loop    : first version -> quick check; preview has no numbers; review with one zoom; the first finish gets
            the reminder, the second delivers
  fixes   : a patch with a bad path is an error for the agent, not a crash; a checker session that tries a tool
            (or writes one out as text) is replaced and the run stays valid; full reviews come automatically at action 12 and near the end
  oneshot : one submission of the hidden answer is delivered with the reference pictures in the opening

    python3 tests/selftest.py /tmp/motion-replica-selftest
"""
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from replica.proxy import Proxy  # noqa: E402
from replica.run import ROOT, run  # noqa: E402

PACK = ROOT / 'tasks' / 'material_wave_loading'


class Scripted:
    def __init__(self, replies):
        self.replies, self.seen = list(replies), []
        self.identity = {'model': 'scripted'}

    def send(self, text, images):
        self.seen.append((text, [Path(p).name for p in images]))
        return self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]  # the last reply repeats

    def close(self):
        pass


class ToolUser(Scripted):
    def send(self, text, images):
        raise RuntimeError('tool_use_invalidates_trial: {"session_update": "tool_call"}')


def factory(sessions):
    it = iter(sessions)
    return lambda timeout: next(it)


def check(name, condition, ok):
    print(('PASS ' if condition else 'FAIL ') + name)
    ok.append(condition)


def main(root):
    root = Path(root)
    shutil.rmtree(root, ignore_errors=True)
    answer = json.loads((PACK / 'hidden/answer.json').read_text())
    shifted = json.loads(json.dumps(answer))  # content 20 px right and every keyframe 6 frames late
    for layer in shifted['layers']:
        if layer['ks']['a'].get('a') == 0:
            layer['ks']['a']['k'][0] -= 20

    def delay(node):
        if isinstance(node, dict):
            if isinstance(node.get('t'), (int, float)) and 's' in node:
                node['t'] += 6
            for v in node.values():
                delay(v)
        elif isinstance(node, list):
            for v in node:
                delay(v)
    delay(shifted['layers'])
    act = lambda **kw: json.dumps(kw)
    ok = []
    proxy = Proxy()
    try:
        # loop
        agent = Scripted([act(action='set_ir', ir=shifted), act(action='preview', times=[0, 0.5]), act(action='review'),
                          act(action='finish'), act(action='finish')])
        quick = Scripted(['The dots are right of the target and late. CHANGE: same'])
        reviewer = Scripted(['{"zoom":[0.2,0.6]}', 'The dots are about 20 px right of the target and 0.2 s late.\nREMAINING: yes'])
        r = run('scripted', 'loop', PACK, root / 'loop', proxy, new_session=factory([agent, quick, reviewer]))
        replies = [t for t, _ in agent.seen]
        check('loop: quick check follows the first version', 'Quick check of version 1' in replies[1], ok)
        check('loop: preview carries no numbers', 'match' not in replies[2] and agent.seen[2][1] == ['preview_001.png'], ok)
        check('loop: checker zoomed and the review reached the agent',
              reviewer.seen[-1][1] == ['review_001_zoom.png'] and '20 px right' in replies[3], ok)
        check('loop: first finish gets the reminder, second delivers',
              replies[4].startswith('Not finished yet') and r['ended'] == 'finish' and r['result']['delivered'], ok)
        check('loop: final filmstrip written', (root / 'loop' / 'final_strip.png').exists(), ok)

        # fixes
        replies = [act(action='set_ir', ir=shifted), act(action='patch_ir', ops=[{'op': 'replace', 'path': '/layers/0/ip/a/s', 'value': 1}])]
        replies += [act(action='patch_ir', ops=[{'op': 'replace', 'path': '/layers/0/nm', 'value': f'n{i}'}]) for i in range(21)]
        agent = Scripted(replies + [act(action='finish')])
        checkers = [ToolUser(['x']), Scripted(['<｜DSML｜ invoke name="read">'])] + [Scripted(['Dots are late. CHANGE: same\nREMAINING: yes']) for _ in range(40)]
        r = run('scripted', 'loop', PACK, root / 'fixes', proxy, new_session=factory([agent] + checkers))
        texts = [t for t, _ in agent.seen]
        auto = [i for i, t in enumerate(texts) if t.startswith('Accepted') and 'Automatic full review' in t]
        check('fixes: bad patch path is an error message', texts[2].startswith('Error: ops[0]') and r['valid'], ok)
        check('fixes: checker that calls or writes out a tool is replaced, run valid',
              r['stats'].get('checker_tool_retries') == 2 and 'could not answer' in texts[1] and r['valid'], ok)
        check(f'fixes: automatic full reviews at agent turns {auto}', auto == [12, 20], ok)

        # oneshot
        agent = Scripted([act(action='submit', ir=answer)])
        r = run('scripted', 'oneshot', PACK, root / 'oneshot', proxy, new_session=factory([agent]))
        check('oneshot: delivered after one submission', r['ended'] == 'finish' and r['result']['delivered'], ok)
        check('oneshot: opening has overview + reference pictures',
              agent.seen[0][1][0] == 'overview.png' and 'ref_curves.png' in agent.seen[0][1], ok)
    finally:
        proxy.close()
    print(f'{sum(ok)}/{len(ok)} checks passed')
    sys.exit(0 if all(ok) else 1)


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else '/tmp/motion-replica-selftest')
