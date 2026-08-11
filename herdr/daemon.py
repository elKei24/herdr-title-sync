#!/usr/bin/env python3
"""Mirror agent terminal titles onto herdr tab labels."""

import json
import os
import subprocess
import sys
import time

POLL_SECONDS = 2.0
MAX_LIST_FAILURES = 5
PLUGIN_ID = "elkei24.title-sync"


def parse_agents(raw):
    return json.loads(raw)["result"]["agents"]


def plan_renames(agents, last_set):
    """Renames to apply, as (tab_id, title) pairs.

    First agent with a non-empty title claims its tab; a rename is emitted
    only when the title differs from what we last set for that tab.
    """
    renames = []
    claimed = set()
    for agent in agents:
        tab_id = agent.get("tab_id")
        title = (agent.get("terminal_title_stripped") or "").strip()
        if not tab_id or not title or tab_id in claimed:
            continue
        claimed.add(tab_id)
        if last_set.get(tab_id) != title:
            renames.append((tab_id, title))
    return renames


def acquire_lock(lock_path):
    """Write our pid to lock_path; False if a live process already holds it."""
    pid = None
    try:
        with open(lock_path) as fh:
            pid = int(fh.read().strip())
    except (FileNotFoundError, ValueError):
        pass
    if pid is not None:
        try:
            os.kill(pid, 0)
            return False
        except ProcessLookupError:
            pass
        except PermissionError:
            return False
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    with open(lock_path, "w") as fh:
        fh.write(str(os.getpid()))
    return True


def herdr_bin():
    return os.environ.get("HERDR_BIN_PATH") or "herdr"


def state_dir():
    return os.environ.get("HERDR_PLUGIN_STATE_DIR") or os.path.expanduser(
        "~/.local/state/herdr/plugins/" + PLUGIN_ID
    )


def log(message):
    print(message, flush=True)


def run_cycle(bin_path, last_set, run=subprocess.run):
    proc = run([bin_path, "agent", "list"], capture_output=True, text=True, timeout=10)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "agent list failed")
    for tab_id, title in plan_renames(parse_agents(proc.stdout), last_set):
        result = run(
            [bin_path, "tab", "rename", tab_id, title],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            last_set[tab_id] = title
            log("renamed %s -> %r" % (tab_id, title))
        else:
            log("rename failed for %s: %s" % (tab_id, result.stderr.strip()))


def main():
    lock_path = os.path.join(state_dir(), "daemon.pid")
    if not acquire_lock(lock_path):
        log("title-sync daemon already running, exiting")
        return 0
    bin_path = herdr_bin()
    log("title-sync daemon started (pid %d)" % os.getpid())
    last_set = {}
    failures = 0
    while True:
        time.sleep(POLL_SECONDS)
        try:
            run_cycle(bin_path, last_set)
            failures = 0
        except Exception as exc:
            failures += 1
            log("cycle failed (%d/%d): %s" % (failures, MAX_LIST_FAILURES, exc))
            if failures >= MAX_LIST_FAILURES:
                log("herdr unreachable, exiting")
                return 1


if __name__ == "__main__":
    sys.exit(main())
