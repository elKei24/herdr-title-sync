import json
import os
import tempfile
import unittest

from herdr.daemon import (
    acquire_lock,
    herdr_bin,
    parse_agents,
    parse_tabs,
    plan_renames,
    run_cycle,
    state_dir,
)


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


class ParseTabsTest(unittest.TestCase):
    def test_parses_tab_list_into_label_map(self):
        raw = json.dumps(
            {
                "id": "cli:tab:list",
                "result": {
                    "tabs": [
                        {"tab_id": "w1:t1", "label": "1", "focused": True},
                        {"tab_id": "w1:t2", "label": "Fix bug", "focused": False},
                    ],
                    "type": "tab_list",
                },
            }
        )
        self.assertEqual(parse_tabs(raw), {"w1:t1": "1", "w1:t2": "Fix bug"})


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


class FakeProc:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def fake_run(script):
    """Returns a subprocess.run stand-in reading responses from `script`.

    `script` maps a command tuple to a FakeProc. Records calls in .calls.
    """
    def run(argv, **kwargs):
        run.calls.append(tuple(argv))
        return script[tuple(argv)]

    run.calls = []
    return run


def agent_list_json(*agents):
    return json.dumps({"id": "x", "result": {"agents": list(agents), "type": "agent_list"}})


def tab_list_json(labels):
    tabs = [{"tab_id": tab_id, "label": label} for tab_id, label in labels.items()]
    return json.dumps({"id": "x", "result": {"tabs": tabs, "type": "tab_list"}})


class RunCycleTest(unittest.TestCase):
    def test_renames_tab_whose_label_differs(self):
        run = fake_run({
            ("herdr", "agent", "list"): FakeProc(stdout=agent_list_json(agent("w1:t1", "Fix bug"))),
            ("herdr", "tab", "list"): FakeProc(stdout=tab_list_json({"w1:t1": "1"})),
            ("herdr", "tab", "rename", "w1:t1", "Fix bug"): FakeProc(),
        })
        run_cycle("herdr", run=run)
        self.assertIn(("herdr", "tab", "rename", "w1:t1", "Fix bug"), run.calls)

    def test_overwrites_manual_rename_even_when_title_unchanged(self):
        run = fake_run({
            ("herdr", "agent", "list"): FakeProc(stdout=agent_list_json(agent("w1:t1", "Fix bug"))),
            ("herdr", "tab", "list"): FakeProc(stdout=tab_list_json({"w1:t1": "my manual label"})),
            ("herdr", "tab", "rename", "w1:t1", "Fix bug"): FakeProc(),
        })
        run_cycle("herdr", run=run)
        self.assertIn(("herdr", "tab", "rename", "w1:t1", "Fix bug"), run.calls)

    def test_failed_rename_does_not_raise(self):
        run = fake_run({
            ("herdr", "agent", "list"): FakeProc(stdout=agent_list_json(agent("w1:t1", "Fix bug"))),
            ("herdr", "tab", "list"): FakeProc(stdout=tab_list_json({"w1:t1": "1"})),
            ("herdr", "tab", "rename", "w1:t1", "Fix bug"): FakeProc(returncode=1, stderr="tab_not_found"),
        })
        run_cycle("herdr", run=run)

    def test_failed_agent_list_raises(self):
        run = fake_run({
            ("herdr", "agent", "list"): FakeProc(returncode=1, stderr="no server"),
        })
        with self.assertRaises(RuntimeError):
            run_cycle("herdr", run=run)

    def test_failed_tab_list_raises(self):
        run = fake_run({
            ("herdr", "agent", "list"): FakeProc(stdout=agent_list_json(agent("w1:t1", "Fix bug"))),
            ("herdr", "tab", "list"): FakeProc(returncode=1, stderr="no server"),
        })
        with self.assertRaises(RuntimeError):
            run_cycle("herdr", run=run)

    def test_no_rename_when_label_matches_title(self):
        run = fake_run({
            ("herdr", "agent", "list"): FakeProc(stdout=agent_list_json(agent("w1:t1", "Fix bug"))),
            ("herdr", "tab", "list"): FakeProc(stdout=tab_list_json({"w1:t1": "Fix bug"})),
        })
        run_cycle("herdr", run=run)
        self.assertEqual(
            run.calls, [("herdr", "agent", "list"), ("herdr", "tab", "list")]
        )


class EnvTest(unittest.TestCase):
    def test_herdr_bin_prefers_env(self):
        os.environ["HERDR_BIN_PATH"] = "/opt/herdr"
        try:
            self.assertEqual(herdr_bin(), "/opt/herdr")
        finally:
            del os.environ["HERDR_BIN_PATH"]

    def test_herdr_bin_falls_back_to_path_lookup(self):
        os.environ.pop("HERDR_BIN_PATH", None)
        self.assertEqual(herdr_bin(), "herdr")

    def test_state_dir_prefers_env(self):
        os.environ["HERDR_PLUGIN_STATE_DIR"] = "/tmp/state"
        try:
            self.assertEqual(state_dir(), "/tmp/state")
        finally:
            del os.environ["HERDR_PLUGIN_STATE_DIR"]

    def test_state_dir_fallback(self):
        os.environ.pop("HERDR_PLUGIN_STATE_DIR", None)
        self.assertEqual(
            state_dir(),
            os.path.expanduser("~/.local/state/herdr/plugins/elkei24.title-sync"),
        )


if __name__ == "__main__":
    unittest.main()
