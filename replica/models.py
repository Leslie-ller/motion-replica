"""Model sessions through the Devin desktop client's ACP interface (Ask mode, every built-in tool disabled).

The model has no callable tools: it acts only by writing JSON actions as text. If the client still reports a
tool call, the session raises and the trial is recorded as invalid. No credentials are read here: the Devin
process uses its own stored login (DEVIN_HOME profile). Private reasoning events are dropped, never stored.
"""
import base64
import json
import os
import queue
import signal
import subprocess
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEVIN_BIN = os.environ.get('DEVIN_BIN', '/Applications/Devin.app/Contents/Resources/app/extensions/windsurf/devin/bin/devin')
DEVIN_HOME = Path(os.environ.get('DEVIN_HOME', Path.home() / '.local/share/devin-worker'))
NO_TOOLS = ROOT / 'config' / 'devin-no-tools.json'
POLICY = ('You are taking part in an animation-reproduction experiment. You have no tools: do not run commands, '
          'read files, browse, or call functions. Act only by writing the JSON actions described in the user '
          'messages; the experiment harness executes them and replies with results and images.')


class RPC:
    """JSON-RPC over the client's stdin/stdout. Any tool request or tool call raises *_invalidates_trial."""

    def __init__(self, argv, cwd, timeout, env):
        self.deadline = time.monotonic() + timeout
        self.proc = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, text=True, start_new_session=True)
        self.q = queue.Queue()
        self.counter = 0
        self.events = []
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for line in self.proc.stdout:
            try:
                self.q.put(json.loads(line))
            except ValueError:
                pass
        self.q.put(None)

    def send(self, data):
        self.proc.stdin.write(json.dumps(dict(data, jsonrpc='2.0'), ensure_ascii=False) + '\n')
        self.proc.stdin.flush()

    def receive(self):
        try:
            message = self.q.get(timeout=max(0.0, self.deadline - time.monotonic()))
        except queue.Empty:
            raise TimeoutError('client deadline exceeded') from None
        if message is None:
            raise RuntimeError('client exited before completion')
        method, params = message.get('method', ''), message.get('params', {})
        update = params.get('update', {})
        if update.get('sessionUpdate') == 'agent_thought_chunk' or 'reasoning' in method.lower():
            return {}
        if method and 'id' in message:  # the client asks us to approve something: refuse, invalidate
            outcome = {'result': {'outcome': {'outcome': 'cancelled'}}} if method == 'session/request_permission' else \
                      {'error': {'code': -32601, 'message': 'Tools disabled'}}
            self.send({'id': message['id'], **outcome})
            raise RuntimeError('tool_request_invalidates_trial: ' + method)
        if update.get('sessionUpdate') in ('tool_call', 'tool_call_update'):
            # protocol metadata only, never tool arguments
            raise RuntimeError('tool_use_invalidates_trial: ' + json.dumps(
                {'session_update': update.get('sessionUpdate'), 'kind': update.get('kind'), 'status': update.get('status')}))
        if method == 'session/update' and update.get('sessionUpdate') == 'agent_message_chunk':
            self.events.append(message)
        return message

    def call(self, method, params):
        self.counter += 1
        ident = self.counter
        self.send({'id': ident, 'method': method, 'params': params})
        while True:
            response = self.receive()
            if response.get('id') == ident and 'method' not in response:
                if 'error' in response:
                    raise RuntimeError(method + ': ' + str(response['error'])[:1500])
                return response.get('result', {})

    def close(self):
        try:
            os.killpg(self.proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            self.proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            os.killpg(self.proc.pid, signal.SIGKILL)
            self.proc.wait(timeout=3)


class DevinSession:
    """One conversation with one pinned model. The selected model is checked against the client's
    acknowledgement; there is no fallback."""
    model = None

    def __init__(self, timeout):
        self.tmp = tempfile.TemporaryDirectory(prefix='motion-replica-')
        cwd = Path(self.tmp.name)
        env = dict(os.environ, XDG_DATA_HOME=str(DEVIN_HOME), XDG_CONFIG_HOME=str(Path.home() / '.config/devin-worker'),
                   XDG_CACHE_HOME=str(Path.home() / '.cache/devin-worker'))
        self.rpc = RPC([DEVIN_BIN, '--config', str(NO_TOOLS), 'acp'], cwd, timeout, env)
        self.timeout = timeout
        try:
            self.rpc.call('initialize', {'protocolVersion': 1, 'clientCapabilities': {},
                                         'clientInfo': {'name': 'devin-acp-run', 'version': '0'}})
            self.session = self.rpc.call('session/new', {'cwd': str(cwd), 'mcpServers': []})['sessionId']
            self.rpc.call('session/set_mode', {'sessionId': self.session, 'modeId': 'ask'})
            response = self.rpc.call('session/set_config_option', {'sessionId': self.session, 'configId': 'model', 'value': self.model})
            observed = next((x for x in response.get('configOptions', []) if x.get('id') == 'model'), {}).get('currentValue')
            if observed != self.model:
                raise RuntimeError(f'Devin did not confirm {self.model}: {observed}')
        except BaseException:
            self.close()
            raise
        self.identity = {'model': self.model, 'client': 'Devin ACP, Ask mode, tools disabled', 'session_id': self.session}

    def send(self, text, images):
        self.rpc.deadline = time.monotonic() + self.timeout
        start = len(self.rpc.events)
        blocks = [{'type': 'text', 'text': POLICY + '\n\n' + text}]
        blocks += [{'type': 'image', 'mimeType': 'image/png', 'data': base64.b64encode(Path(p).read_bytes()).decode()}
                   for p in images]
        response = self.rpc.call('session/prompt', {'sessionId': self.session, 'prompt': blocks})
        if response.get('stopReason') != 'end_turn':
            raise RuntimeError('incomplete response: ' + str(response.get('stopReason')))
        return ''.join(x['params']['update']['content'].get('text', '') for x in self.rpc.events[start:])

    def close(self):
        try:
            if hasattr(self, 'rpc'):
                self.rpc.close()
        finally:
            self.tmp.cleanup()


class DeepSeekFlash(DevinSession):
    model = 'deepseek-v4-1-flash-high'


class SWE2(DevinSession):
    model = 'swe-2-high'


MODELS = {'dsflash': DeepSeekFlash, 'swe2': SWE2}
