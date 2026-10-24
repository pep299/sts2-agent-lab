"""learn公開ホストのJSON通信。ゲームアプリやDLLの複製・準備は行わない。"""

import json
import os
from pathlib import Path
import selectors
import subprocess
import time

from backends.learn_dll.observation import normalize_observation
from backends.common.policy_io import PolicyFault


class LearnEnvironment:
    def __init__(self, root, dotnet, output, timeout=35):
        root = Path(root).resolve()
        self.output = Path(output).resolve()
        host = root / 'addons/public-observation/Sts2DllRecorder/bin/Release/net9.0/Sts2DllRecorder.dll'
        if not host.is_file():
            raise FileNotFoundError(f'ビルド済み公開ホストがない: {host}')
        self.host = host
        self.output.mkdir(parents=True, exist_ok=False)
        self.stderr = (self.output / 'host-stderr.log').open('x')
        try:
            self.process = subprocess.Popen([str(dotnet), str(host), '--log', str(self.output / 'events.jsonl')],
                    cwd=root, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.stderr, bufsize=0)
        except BaseException:
            self.stderr.close()
            raise
        os.set_blocking(self.process.stdout.fileno(), False)
        self.timeout = timeout
        self.steps = 0
        self.decision_id = 0
        self.last = None

    def request(self, command, deadline=None):
        end = min(time.monotonic() + self.timeout, deadline or float('inf'))
        payload = (json.dumps(command) + '\n').encode()
        self.process.stdin.write(payload)
        self.process.stdin.flush()
        response = bytearray()
        with selectors.DefaultSelector() as selector:
            selector.register(self.process.stdout, selectors.EVENT_READ)
            while b'\n' not in response:
                left = end - time.monotonic()
                if left <= 0 or not selector.select(left):
                    raise TimeoutError('learn_public_host_timeout')
                chunk = os.read(self.process.stdout.fileno(), 65536)
                if not chunk:
                    raise RuntimeError(f'learn_public_host_exit:{self.process.poll()}')
                response.extend(chunk)
                if len(response) > 32 * 1024 * 1024:
                    raise RuntimeError('learn_public_host_response_too_large')
        line, extra = response.split(b'\n', 1)
        if extra.strip():
            raise RuntimeError('learn_public_host_unsolicited_output')
        observation = json.loads(line)
        if 'error' in observation:
            raise RuntimeError('learn_public_host_error:' + observation['error'])
        self.decision_id += 1
        self.actions = observation['actions']
        self.last = {'decision_id': self.decision_id, 'observation': normalize_observation(observation)}
        return self.last

    def reset(self, seed, deadline=None):
        self.steps = 0
        self.decision_id = 0
        return self.request({'cmd': 'reset', 'seed': seed, 'character': 'IRONCLAD', 'ascension': 0,
                             'actGeneration': 'seeded_all_unlocked'}, deadline)

    def step(self, decision, deadline=None):
        if not any(a['id'] == decision['action_id'] for a in self.last['observation']['actions']):
            raise PolicyFault('行動IDが公開候補にない')
        actions = self.actions
        if decision['action_id'] == 'choose_cards:':
            if not any(a['detail'].get('parameter') == 'cardIndices' for a in actions):
                raise PolicyFault('カード番号を受け付ける候補がない')
            indices = decision.get('indices')
            selection = self.last['observation']['state']['selection']
            if (not isinstance(indices, list) or any(type(i) is not int or not 0 <= i < len(selection['cards']) for i in indices)
                    or len(set(indices)) != len(indices) or not selection['min'] <= len(indices) <= selection['max']):
                raise PolicyFault('カード番号または選択枚数が公開候補の制約外')
            command = {'cmd': 'step', 'cardIndices': indices}
        else:
            action = next((a for a in actions if a['id'] == decision['action_id']), None)
            if action is None:
                raise PolicyFault('行動IDが公開候補にない')
            command = {'cmd': 'step', 'index': action['detail']['nativeOptionIndex']}
        result = self.request(command, deadline)
        self.steps += 1
        return result

    def close(self):
        if self.process.poll() is None:
            try:
                self.process.stdin.write(b'{"cmd":"close"}\n')
                self.process.stdin.flush()
                self.process.wait(timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                self.process.terminate()
                try:
                    self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=3)
        self.process.stdin.close()
        self.process.stdout.close()
        self.stderr.close()
