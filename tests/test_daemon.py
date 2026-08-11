import json
import os
import subprocess
import tempfile
import unittest
from unittest import mock

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
    def test_acquires_and_writes_pid(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "sub", "daemon.pid")
            lock = acquire_lock(path)
            self.assertIsNotNone(lock)
            with open(path) as fh:
                self.assertEqual(int(fh.read()), os.getpid())
            lock.close()

    def test_second_acquire_fails_while_held(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "daemon.pid")
            lock = acquire_lock(path)
            self.assertIsNotNone(lock)
            self.assertIsNone(acquire_lock(path))
            lock.close()

    def test_reacquires_after_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "daemon.pid")
            acquire_lock(path).close()
            second = acquire_lock(path)
            self.assertIsNotNone(second)
            second.close()


def proc(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


def fake_run(script):
    """Returns a subprocess.run stand-in reading responses from `script`.

    `script` maps a command tuple to a CompletedProcess. Records calls in .calls.
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
        # also covers manual renames: any label != title is overwritten
        run = fake_run({
            ("herdr", "agent", "list"): proc(stdout=agent_list_json(agent("w1:t1", "Fix bug"))),
            ("herdr", "tab", "list"): proc(stdout=tab_list_json({"w1:t1": "my manual label"})),
            ("herdr", "tab", "rename", "w1:t1", "Fix bug"): proc(),
        })
        run_cycle("herdr", run=run)
        self.assertIn(("herdr", "tab", "rename", "w1:t1", "Fix bug"), run.calls)

    def test_failed_rename_does_not_raise(self):
        run = fake_run({
            ("herdr", "agent", "list"): proc(stdout=agent_list_json(agent("w1:t1", "Fix bug"))),
            ("herdr", "tab", "list"): proc(stdout=tab_list_json({"w1:t1": "1"})),
            ("herdr", "tab", "rename", "w1:t1", "Fix bug"): proc(returncode=1, stderr="tab_not_found"),
        })
        run_cycle("herdr", run=run)

    def test_failed_agent_list_raises(self):
        run = fake_run({
            ("herdr", "agent", "list"): proc(returncode=1, stderr="no server"),
        })
        with self.assertRaises(RuntimeError):
            run_cycle("herdr", run=run)

    def test_failed_tab_list_raises(self):
        run = fake_run({
            ("herdr", "agent", "list"): proc(stdout=agent_list_json(agent("w1:t1", "Fix bug"))),
            ("herdr", "tab", "list"): proc(returncode=1, stderr="no server"),
        })
        with self.assertRaises(RuntimeError):
            run_cycle("herdr", run=run)

    def test_no_rename_when_label_matches_title(self):
        run = fake_run({
            ("herdr", "agent", "list"): proc(stdout=agent_list_json(agent("w1:t1", "Fix bug"))),
            ("herdr", "tab", "list"): proc(stdout=tab_list_json({"w1:t1": "Fix bug"})),
        })
        run_cycle("herdr", run=run)
        self.assertEqual(
            run.calls, [("herdr", "agent", "list"), ("herdr", "tab", "list")]
        )

    def test_rename_timeout_does_not_raise(self):
        def run(argv, **kwargs):
            if argv[1] == "tab" and argv[2] == "rename":
                raise subprocess.TimeoutExpired(argv, 10)
            if argv[1:] == ["agent", "list"]:
                return proc(stdout=agent_list_json(agent("w1:t1", "Fix bug")))
            return proc(stdout=tab_list_json({"w1:t1": "1"}))

        run_cycle("herdr", run=run)


class EnvTest(unittest.TestCase):
    def test_herdr_bin_prefers_env(self):
        with mock.patch.dict(os.environ, {"HERDR_BIN_PATH": "/opt/herdr"}):
            self.assertEqual(herdr_bin(), "/opt/herdr")

    def test_herdr_bin_falls_back_to_path_lookup(self):
        with mock.patch.dict(os.environ):
            os.environ.pop("HERDR_BIN_PATH", None)
            self.assertEqual(herdr_bin(), "herdr")

    def test_state_dir_prefers_env(self):
        with mock.patch.dict(os.environ, {"HERDR_PLUGIN_STATE_DIR": "/tmp/state"}):
            self.assertEqual(state_dir(), "/tmp/state")

    def test_state_dir_fallback(self):
        with mock.patch.dict(os.environ):
            os.environ.pop("HERDR_PLUGIN_STATE_DIR", None)
            self.assertEqual(
                state_dir(),
                os.path.expanduser("~/.local/state/herdr/plugins/elkei24.title-sync"),
            )


if __name__ == "__main__":
    unittest.main()
