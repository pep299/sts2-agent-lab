"""JSON Lines方策プロセスの通信・期限・回収。ゲーム環境には依存しない。"""
from pathlib import Path
import json
import os
import selectors
import subprocess
import time

class EnvironmentFault(RuntimeError):pass
class DeclaredLimit(EnvironmentFault):pass
class PolicyFault(RuntimeError):pass

class JsonLinePolicy:
    def __init__(self,command,output,timeout=30,*,cwd=None):
        self.stderr=Path(output).open('x');self.timeout=timeout;self.command=command;self.process=None;self.cwd=cwd
        try:self._start()
        except BaseException:self.stderr.close();raise

    def _start(self):
        if self.stderr.closed:raise PolicyFault('policy_closed')
        self.process=subprocess.Popen(self.command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=self.stderr,bufsize=0,
                cwd=self.cwd)
        os.set_blocking(self.process.stdin.fileno(),False)
        os.set_blocking(self.process.stdout.fileno(),False)

    def __call__(self,boundary,*,run_deadline=None):
        if self.process is None:self._start()
        try:return self._exchange(boundary,run_deadline)
        except BaseException:
            # 遅延応答を次ランで受け取らないよう、失敗した通信路は破棄する。
            self._stop()
            raise

    def _exchange(self,boundary,run_deadline):
        deadline=time.monotonic()+self.timeout
        if run_deadline is not None:deadline=min(deadline,run_deadline)
        payload=memoryview((json.dumps(boundary,ensure_ascii=False)+'\n').encode())
        if len(payload)>32*1024*1024:raise PolicyFault('policy_input_too_large')
        def ready(selector):
            remaining=deadline-time.monotonic()
            if remaining<=0 or not selector.select(remaining):
                if run_deadline is not None and time.monotonic()>=run_deadline:raise DeclaredLimit('declared_wall_time_limit')
                raise PolicyFault('policy_response_timeout')
        with selectors.DefaultSelector() as selector:
            selector.register(self.process.stdin,selectors.EVENT_WRITE)
            while payload:
                ready(selector)
                try:written=os.write(self.process.stdin.fileno(),payload)
                except BlockingIOError:continue
                except BrokenPipeError as error:raise PolicyFault('policy_input_closed') from error
                payload=payload[written:]
            selector.unregister(self.process.stdin)
            selector.register(self.process.stdout,selectors.EVENT_READ)
            response=bytearray()
            while b'\n' not in response:
                ready(selector)
                try:chunk=os.read(self.process.stdout.fileno(),65536)
                except BlockingIOError:continue
                if not chunk:raise PolicyFault('policy_process_exit:'+str(self.process.poll()))
                response.extend(chunk)
                if len(response)>1024*1024:raise PolicyFault('policy_response_too_large')
        line,extra=response.split(b'\n',1)
        if extra.strip():raise PolicyFault('policy_unsolicited_output')
        try:decision=json.loads(line)
        except (ValueError,UnicodeDecodeError) as error:raise PolicyFault('policy_response_not_json') from error
        if not isinstance(decision,dict) or not isinstance(decision.get('action_id'),str):
            raise PolicyFault('policy_response_missing_action_id')
        return decision
    def _stop(self):
        if self.process is None:return
        if self.process.poll() is None:
            self.process.terminate()
            try:self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:self.process.kill();self.process.wait(timeout=3)
        self.process.stdin.close();self.process.stdout.close();self.process=None

    def close(self):
        self._stop();self.stderr.close()
