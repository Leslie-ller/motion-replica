#!/usr/bin/env python3
"""Run one session: one model, one condition, one task. Writes trace.jsonl, result.json and the final
frames into a new folder.

    python3 -m replica.run --model dsflash --condition loop --task browser --out runs/browser-1
"""
import argparse
import json
import re
import time
import traceback
from pathlib import Path

from . import pictures
from .loop import Session
from .models import MODELS
from .prompts import opening

ROOT = Path(__file__).resolve().parent.parent


def parse_action(text):
    """First JSON object in the reply that has an "action" key (code fences and prose are ignored)."""
    decoder = json.JSONDecoder()
    index = text.find('{')
    while index != -1:
        try:
            value, _ = decoder.raw_decode(text, index)
            if isinstance(value, dict) and 'action' in value:
                return value
        except ValueError:
            pass
        index = text.find('{', index + 1)
    return None


def json_problem(text):
    """Explain why no action was found: a written-out tool call, a syntax error with context, or no JSON at all."""
    # Some models write their native tool-call markup (e.g. DeepSeek's DSML) as text; nothing runs, so say so.
    call = re.search(r'invoke name=\\?"([A-Za-z_]+)', text)
    if 'DSML' in text or call:
        name = f' ({call.group(1)})' if call else ''
        return (f'Error: you wrote a tool call{name}. You have no tools here, so nothing ran. Reply with exactly one '
                f'JSON action object as plain text, e.g. {{"action":"preview","times":[0.5]}}.')
    index = text.find('{')
    if index == -1:
        return 'Error: no JSON object with an "action" key was found in your reply.'
    try:
        json.JSONDecoder().raw_decode(text, index)
        return 'Error: your JSON has no "action" key.'
    except ValueError as error:
        pos = getattr(error, 'pos', None)
        where = f' near: ...{text[max(index, pos - 60):pos]}<<HERE>>{text[pos:pos + 30]}...' if pos is not None else ''
        return f'Error: your JSON is invalid ({getattr(error, "msg", error)} at character {pos}){where}'


def run(model, condition, pack, out, proxy, steps=24, minutes=25, client_timeout=600, new_session=None):
    """new_session(timeout) -> a model session; defaults to MODELS[model]. The checker uses the same factory,
    so it is always the same model as the agent. A client tool call makes the result invalid."""
    pack, out = Path(pack), Path(out)
    new_session = new_session or MODELS[model]
    session = Session(pack, out, condition, proxy, lambda: new_session(timeout=client_timeout), steps)
    trace = open(out / 'trace.jsonl', 'a')
    log = lambda **kw: (trace.write(json.dumps(kw, ensure_ascii=False) + '\n'), trace.flush())
    record = {'model': model, 'condition': condition, 'task': session.task['id'], 'steps_budget': session.steps,
              'minutes_budget': minutes, 'started': time.strftime('%Y-%m-%dT%H:%M:%S%z')}
    agent, started, used, ended = None, time.monotonic(), 0, 'budget'
    try:
        agent = new_session(timeout=client_timeout)
        record['client'] = agent.identity
        text = opening(condition, session.task, session.steps, minutes)
        pack_images, _ = pictures.reference_pack([session.ref[t] for t in session.times], session.times, out)
        images = [pack / 'public/overview.png'] + pack_images
        while used < session.steps:
            if time.monotonic() - started > minutes * 60:
                ended = 'deadline'
                break
            t0 = time.monotonic()
            reply = agent.send(text, images)
            used += 1
            log(step=used, kind='model', seconds=round(time.monotonic() - t0, 2), reply=reply)
            action, finished = parse_action(reply), False
            if action is None:
                session.stats['invalid_actions'] += 1
                text, images = json_problem(reply), []
            else:
                try:
                    text, images, finished = session.step(action)
                except ValueError as error:
                    session.stats['invalid_actions'] += 1
                    text, images = f'Error: {error}', []
            log(step=used, kind='harness', action=(action or {}).get('action'), text=text[:4000],
                images=[str(p) for p in images])
            if finished:
                ended = 'finish'
                break
            left = session.steps - used
            text += f'\n\n[{left} action(s) and {max(0, minutes - (time.monotonic() - started) / 60):.1f} min left]'
            if left == 1:
                text += ' This is your last action: send finish now or your current state is delivered as is.'
    except Exception as error:
        ended = 'error'
        record['error'] = f'{type(error).__name__}: {error}'[:1500]
        log(kind='error', error=traceback.format_exc()[-4000:])
    finally:
        if agent is not None:
            try:
                agent.close()
            except Exception:
                pass
    error = record.get('error', '')
    record.update(ended=ended, actions_used=used, wall_seconds=round(time.monotonic() - started, 1),
                  versions=session.version, stats=session.stats,
                  tool_violation='invalidates_trial' in error)
    # A tool call by the agent invalidates the run; any other crash is the harness's, also invalid.
    record['valid'] = ended != 'error'
    record['result'] = session.deliver() if record['valid'] else {'delivered': False}
    (out / 'result.json').write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n')
    trace.close()
    return record


def main():
    from .proxy import Proxy
    p = argparse.ArgumentParser()
    p.add_argument('--model', choices=list(MODELS), required=True)
    p.add_argument('--condition', choices=['loop', 'oneshot'], default='loop')
    p.add_argument('--task', required=True, help='a folder name in tasks/')
    p.add_argument('--out', type=Path, required=True, help='new folder for this run')
    p.add_argument('--steps', type=int, default=24)
    p.add_argument('--minutes', type=float, default=25)
    a = p.parse_args()
    a.out = a.out.resolve()
    proxy = Proxy()
    try:
        r = run(a.model, a.condition, ROOT / 'tasks' / a.task, a.out, proxy, a.steps, a.minutes)
    finally:
        proxy.close()
    print(json.dumps({k: r.get(k) for k in ('task', 'condition', 'ended', 'actions_used', 'valid', 'error')}, ensure_ascii=False))
    print('result filmstrip:', a.out / 'final_strip.png')


if __name__ == '__main__':
    main()
