"""実プロセスでJSON通信の期限・破損・再起動を検証する。"""
from pathlib import Path
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from backends.common.policy_io import JsonLinePolicy, PolicyFault, DeclaredLimit


class PolicyIOTests(unittest.TestCase):
    def policy(self,source,timeout=.3):
        directory=tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        policy=JsonLinePolicy([sys.executable,'-u','-c',source],Path(directory.name)/'stderr.log',timeout)
        self.addCleanup(policy.close)
        return policy

    def test_valid_utf8_response(self):
        policy=self.policy('import sys,json; value=json.loads(sys.stdin.readline()); print(json.dumps({"action_id":value["label"]},ensure_ascii=False))')
        self.assertEqual(policy({'label':'選択:0'}),{'action_id':'選択:0'})

    def test_partial_line_obeys_deadline(self):
        policy=self.policy('import sys,time; sys.stdin.readline(); sys.stdout.write("{"); sys.stdout.flush(); time.sleep(5)')
        started=time.monotonic()
        with self.assertRaisesRegex(PolicyFault,'policy_response_timeout'):policy({'decision_id':1})
        self.assertLess(time.monotonic()-started,1.5)

    def test_full_input_pipe_obeys_deadline(self):
        policy=self.policy('import time; time.sleep(5)')
        started=time.monotonic()
        with self.assertRaisesRegex(PolicyFault,'policy_response_timeout'):policy({'observation':'x'*1024*1024})
        self.assertLess(time.monotonic()-started,1.5)

    def test_exit_without_response(self):
        policy=self.policy('import sys; sys.stdin.readline()')
        with self.assertRaisesRegex(PolicyFault,'policy_process_exit'):policy({'decision_id':1})

    def test_run_deadline_preempts_longer_policy_timeout(self):
        policy=self.policy('import sys,time; sys.stdin.readline(); time.sleep(5)',timeout=5)
        started=time.monotonic()
        with self.assertRaisesRegex(DeclaredLimit,'declared_wall_time_limit'):
            policy({'decision_id':1},run_deadline=started+.1)
        self.assertLess(time.monotonic()-started,1.5)

    def test_oversized_response_rejected(self):
        policy=self.policy('import sys; sys.stdin.readline(); sys.stdout.write("x"*(1024*1024+1)); sys.stdout.flush()')
        with self.assertRaisesRegex(PolicyFault,'policy_response_too_large'):policy({'decision_id':1})

    def test_failed_exchange_cannot_supply_the_next_runs_response(self):
        source='''import sys,json,time
for line in sys.stdin:
    value=json.loads(line)
    if value['action_id']=='old':time.sleep(.5)
    print(json.dumps(value),flush=True)
'''
        for failure in ['policy_timeout','run_deadline']:
            with self.subTest(failure=failure):
                policy=self.policy(source,timeout=.15)
                deadline=time.monotonic()+.1 if failure=='run_deadline' else None
                expected=DeclaredLimit if deadline is not None else PolicyFault
                with self.assertRaises(expected):policy({'action_id':'old'},run_deadline=deadline)
                policy.timeout=1
                self.assertEqual(policy({'action_id':'new'}),{'action_id':'new'})

    def test_malformed_reply_cannot_leave_a_queued_response(self):
        source='''import sys,json,time
for line in sys.stdin:
    value=json.loads(line)
    if value['action_id']=='old':
        print('invalid',flush=True)
        time.sleep(.05)
    print(json.dumps(value),flush=True)
'''
        policy=self.policy(source)
        with self.assertRaisesRegex(PolicyFault,'policy_response_not_json'):policy({'action_id':'old'})
        self.assertEqual(policy({'action_id':'new'}),{'action_id':'new'})


if __name__ == '__main__':
    unittest.main()
