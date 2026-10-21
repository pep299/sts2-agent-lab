"""Exercise policy timeout behavior with real subprocess pipe failures."""
from pathlib import Path
import sys
import signal
import subprocess
import tempfile
import time
import unittest

from batch import JsonLinePolicy, PolicyFault
from runtime import OwnedProcess,unreviewed_native_errors,DeclaredLimit
from adapter import resolved_successors


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


class OwnedProcessTests(unittest.TestCase):
    def test_collects_own_exit_and_resource_usage(self):
        process=OwnedProcess([sys.executable,'-c','data=bytearray(16*1024*1024)'])
        self.assertEqual(process.wait(3),0)
        self.assertEqual(process.poll(),0)
        self.assertGreater(process.usage['peakRssBytes'],0)

    def test_timeout_then_kill_reaps_same_child(self):
        process=OwnedProcess([sys.executable,'-c','import time; time.sleep(5)'])
        try:
            with self.assertRaises(subprocess.TimeoutExpired):process.wait(.05)
        finally:process.kill();process.wait(3)
        self.assertEqual(process.returncode,-signal.SIGKILL)
        self.assertIsNotNone(process.usage)

class NativeErrorLogTests(unittest.TestCase):
    def test_known_restricted_os_diagnostic_is_optional(self):
        log='[ERROR] System.IndexOutOfRangeException: Index was outside the bounds of the array.\n' \
            '   at MegaCrit.Sts2.Core.Debug.OsDebugInfo.FormatBytes(Int64 bytes)\n' \
            '   at MegaCrit.Sts2.Core.Debug.OsDebugInfo.GetSystemInfoString()\n'
        self.assertEqual(unreviewed_native_errors(log),[])

    def test_other_errors_are_not_suppressed_by_optional_diagnostic_filter(self):
        log='[ERROR] System.IndexOutOfRangeException: Index was outside the bounds of the array.\n' \
            '   at GameAction.Apply()\n'
        errors=unreviewed_native_errors(log)
        self.assertEqual(len(errors),1)
        self.assertIn('GameAction.Apply()',errors[0])

class NestedAfterstateTests(unittest.TestCase):
    def test_parent_afterstate_waits_for_child_choice(self):
        pending={'phase':'card_selection'};resolved={'phase':'shop'}
        rows=[{'kind':'action_successor','actionSequence':1,'data':{'observation':pending}},
              {'kind':'action_successor','actionSequence':2,'data':{'observation':resolved}},
              {'kind':'nested_action_closed','actionSequence':1,'data':{'observation':resolved}}]
        successors,origins=resolved_successors(rows)
        self.assertIs(successors[1],resolved)
        self.assertIs(successors[2],resolved)
        self.assertEqual(origins[1],'nested_action_closed')


if __name__=='__main__':unittest.main()
