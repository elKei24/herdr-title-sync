import json
import os
import tempfile
import unittest

from herdr.daemon import acquire_lock, parse_agents, plan_renames


def agent(tab_id, title):
    return {"tab_id": tab_id, "terminal_title_stripped": title}


class PlanRenamesTest(unittest.TestCase):
    def test_renames_tab_to_agent_title(self):
        renames = plan_renames([agent("w1:t1", "Fix login bug")], {})
        self.assertEqual(renames, [("w1:t1", "Fix login bug")])

    def test_skips_tab_already_at_title(self):
        renames = plan_renames(
            [agent("w1:t1", "Fix login bug")], {"w1:t1": "Fix login bug"}
        )
        self.assertEqual(renames, [])

    def test_renames_again_after_title_change(self):
        renames = plan_renames(
            [agent("w1:t1", "Write tests")], {"w1:t1": "Fix login bug"}
        )
        self.assertEqual(renames, [("w1:t1", "Write tests")])

    def test_first_agent_with_title_wins_per_tab(self):
        renames = plan_renames(
            [agent("w1:t1", "First"), agent("w1:t1", "Second")], {}
        )
        self.assertEqual(renames, [("w1:t1", "First")])

    def test_empty_title_does_not_claim_tab(self):
        renames = plan_renames(
            [agent("w1:t1", ""), agent("w1:t1", "Second")], {}
        )
        self.assertEqual(renames, [("w1:t1", "Second")])

    def test_skips_missing_title_and_missing_tab(self):
        renames = plan_renames(
            [{"tab_id": "w1:t1"}, {"terminal_title_stripped": "No tab"}], {}
        )
        self.assertEqual(renames, [])

    def test_whitespace_title_skipped(self):
        renames = plan_renames([agent("w1:t1", "   ")], {})
        self.assertEqual(renames, [])

    def test_generic_title_is_mirrored(self):
        renames = plan_renames([agent("w1:t1", "Claude Code")], {})
        self.assertEqual(renames, [("w1:t1", "Claude Code")])


class ParseAgentsTest(unittest.TestCase):
    def test_parses_agent_list_output(self):
        raw = json.dumps(
            {"id": "cli:agent:list", "result": {"agents": [agent("w1:t1", "X")], "type": "agent_list"}}
        )
        self.assertEqual(parse_agents(raw), [agent("w1:t1", "X")])


class AcquireLockTest(unittest.TestCase):
    def test_acquires_when_no_lockfile(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "sub", "daemon.pid")
            self.assertTrue(acquire_lock(path))
            with open(path) as fh:
                self.assertEqual(int(fh.read()), os.getpid())

    def test_refuses_when_live_pid_holds_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "daemon.pid")
            with open(path, "w") as fh:
                fh.write(str(os.getpid()))  # this test process is alive
            self.assertFalse(acquire_lock(path))

    def test_steals_lock_from_dead_pid(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "daemon.pid")
            with open(path, "w") as fh:
                fh.write("999999999")
            self.assertTrue(acquire_lock(path))

    def test_steals_lock_with_garbage_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "daemon.pid")
            with open(path, "w") as fh:
                fh.write("not-a-pid")
            self.assertTrue(acquire_lock(path))


if __name__ == "__main__":
    unittest.main()
