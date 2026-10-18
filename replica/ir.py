"""The animation format the agent writes: a Lottie subset that compiles exactly into After Effects.

validate_ir checks a document against the task frame and the verified subset and returns the form the
preview renders; apply_patch applies the agent's JSON Patch edits.
"""
import copy
import re

from .vendor.normalize_proxy import normalize


def frame_tag(t):
    return 't' + format(t, '.6f').rstrip('0').rstrip('.').replace('.', '_')


def frame_times(task):
    return [f / task['fr'] for f in range(int(task['ip']), int(task['op']))]


def validate_ir(ir, task):
    """Returns (normalized_for_preview, notes). Raises ValueError with a message the agent can act on.
    Defaults (linear easing, layer flags) are filled into `ir` in place."""
    if not isinstance(ir, dict):
        raise ValueError('IR must be a JSON object (a Lottie animation)')
    for key in ('w', 'h', 'fr', 'ip', 'op'):
        if ir.get(key) != task[key]:
            raise ValueError(f'IR field {key} must equal {task[key]} (got {ir.get(key)!r})')
    if not isinstance(ir.get('layers'), list) or not ir['layers']:
        raise ValueError('IR needs a non-empty "layers" array')
    ir.setdefault('assets', [])
    ir.setdefault('ddd', 0)
    ir.setdefault('v', '5.9.0')
    for i, layer in enumerate(ir['layers']):
        if not isinstance(layer, dict):
            raise ValueError(f'layers[{i}] must be an object')
        for key, default in (('ddd', 0), ('sr', 1), ('st', 0), ('bm', 0), ('ao', 0)):
            layer.setdefault(key, default)
        for key in ('ty', 'ind', 'ip', 'op', 'ks'):
            if key not in layer:
                raise ValueError(f'layers[{i}] is missing "{key}"')
        for key, meaning in (('ddd', '3D layers'), ('parent', 'parenting'), ('ef', 'effects'),
                             ('tm', 'time remapping'), ('tt', 'track mattes')):
            if layer.get(key):
                raise ValueError(f'layers[{i}]: {meaning} ("{key}") are outside the supported subset')
        if layer['ty'] not in (0, 4):
            raise ValueError(f'layers[{i}]: only shape layers (ty 4) and precomps (ty 0) are supported')
        if layer.get('bm'):
            raise ValueError(f'layers[{i}]: blend modes are unsupported')
    _default_linear(ir)
    inds = [layer['ind'] for layer in ir['layers']]
    if len(set(inds)) != len(inds):
        raise ValueError('layer "ind" values must be unique')
    try:
        return normalize(ir, renderer='svg')
    except ValueError as error:
        raise ValueError(_pointerize(str(error), ir)) from None


LINEAR = {'o': {'x': [1 / 3], 'y': [1 / 3]}, 'i': {'x': [2 / 3], 'y': [2 / 3]}}


def _default_linear(node):
    """Keys without "o"/"i" (other than the last) get exact linear easing. Handles at 1/3 and 2/3 keep AE speed finite."""
    if isinstance(node, dict):
        k = node.get('k')
        if node.get('a') == 1 and isinstance(k, list) and k and all(isinstance(x, dict) and 't' in x for x in k):
            for key in k[:-1]:
                if not key.get('h'):
                    for side in ('o', 'i'):
                        key.setdefault(side, {a: list(b) for a, b in LINEAR[side].items()})
        for child in node.values():
            _default_linear(child)
    elif isinstance(node, list):
        for child in node:
            _default_linear(child)


def _pointerize(message, ir):
    """Rewrite 'root/<ind>.ks.p' style locations from the subset checker as JSON Pointers like /layers/1/ks/p."""
    index = {layer['ind']: i for i, layer in enumerate(ir['layers'])}

    def repl(m):
        ind = int(float(m.group(1)))
        if ind not in index:
            return m.group(0)
        return f'/layers/{index[ind]}' + (m.group(2) or '').replace('.', '/')
    return re.sub(r'root/(\d+(?:\.0)?)((?:\.[A-Za-z]+)*)', repl, message)


def _pointer(path):
    if not isinstance(path, str) or not path.startswith('/'):
        raise ValueError(f'path {path!r} must be a JSON Pointer starting with "/"')
    return [p.replace('~1', '/').replace('~0', '~') for p in path[1:].split('/')]


def apply_patch(doc, ops):
    """JSON Patch subset (add / remove / replace) on a deep copy. Every failure is a ValueError for the agent."""
    if not isinstance(ops, list) or not ops:
        raise ValueError('"ops" must be a non-empty list')
    doc = copy.deepcopy(doc)
    for n, op in enumerate(ops):
        if not isinstance(op, dict) or op.get('op') not in ('add', 'remove', 'replace') or 'path' not in op:
            raise ValueError(f'ops[{n}] must be {{"op": add|remove|replace, "path": ..., "value": ...}}')
        parts = _pointer(op['path'])
        if not parts:
            raise ValueError(f'ops[{n}]: use set_ir to replace the whole document')
        parent = doc
        for p in parts[:-1]:
            try:
                parent = parent[int(p)] if isinstance(parent, list) else parent[p]
            except (KeyError, IndexError, ValueError, TypeError):
                raise ValueError(f'ops[{n}]: path {op["path"]!r} does not exist') from None
        last = parts[-1]
        if op['op'] != 'remove' and 'value' not in op:
            raise ValueError(f'ops[{n}]: "value" is required')
        if not isinstance(parent, (list, dict)):
            raise ValueError(f'ops[{n}]: {op["path"]!r} does not point into an object or array')
        try:
            if isinstance(parent, list):
                index = len(parent) if last == '-' else int(last)
                if op['op'] == 'add':
                    if not 0 <= index <= len(parent):
                        raise IndexError(index)
                    parent.insert(index, op['value'])
                elif op['op'] == 'remove':
                    parent.pop(index)
                else:
                    parent[index] = op['value']
            elif op['op'] == 'remove':
                del parent[last]
            elif op['op'] == 'replace' and last not in parent:
                raise KeyError(last)
            else:
                parent[last] = op['value']
        except (KeyError, IndexError, ValueError):
            raise ValueError(f'ops[{n}]: cannot {op["op"]} at {op["path"]!r}') from None
    return doc
