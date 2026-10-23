"""native環境のプロセス・診断・子選択の記録を検証する。"""
import sys
import signal
import subprocess
import unittest

from runtime import OwnedProcess, unreviewed_native_errors
from adapter import resolved_successors


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
