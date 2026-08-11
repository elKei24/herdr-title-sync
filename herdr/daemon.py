#!/usr/bin/env python3
"""Mirror agent terminal titles onto herdr tab labels."""

import fcntl
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


def parse_tabs(raw):
    return {tab["tab_id"]: tab["label"] for tab in json.loads(raw)["result"]["tabs"]}


def plan_renames(agents, current_labels):
    """Renames to apply, as (tab_id, title) pairs.

    First agent with a non-empty title claims its tab; a rename is emitted
    only when the tab's current label differs from that title.
    """
    renames = []
    claimed = set()
    for agent in agents:
        tab_id = agent.get("tab_id")
        title = (agent.get("terminal_title_stripped") or "").strip()
        if not tab_id or not title or tab_id in claimed:
            continue
        claimed.add(tab_id)
        if current_labels.get(tab_id) != title:
            renames.append((tab_id, title))
    return renames


def acquire_lock(lock_path):
    """Locked file object, or None if another live daemon holds the lock.

    The caller must keep the returned object referenced for the daemon's
    lifetime; the kernel releases the lock when the process exits.
    """
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    fh = open(lock_path, "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return None
    fh.write(str(os.getpid()))
    fh.flush()
    return fh


def herdr_bin():
    return os.environ.get("HERDR_BIN_PATH") or "herdr"


def state_dir():
    return os.environ.get("HERDR_PLUGIN_STATE_DIR") or os.path.expanduser(
        "~/.local/state/herdr/plugins/" + PLUGIN_ID
    )


def log(message):
    print(message, flush=True)


def _herdr(run, bin_path, *args):
    return run([bin_path, *args], capture_output=True, text=True, timeout=10)


def _herdr_or_raise(run, bin_path, *args):
    proc = _herdr(run, bin_path, *args)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "%s failed" % " ".join(args))
    return proc.stdout


def run_cycle(bin_path, run=subprocess.run):
    agents = parse_agents(_herdr_or_raise(run, bin_path, "agent", "list"))
    labels = parse_tabs(_herdr_or_raise(run, bin_path, "tab", "list"))
    for tab_id, title in plan_renames(agents, labels):
        try:
            result = _herdr(run, bin_path, "tab", "rename", tab_id, title)
        except subprocess.TimeoutExpired as exc:
            log("rename failed for %s: %s" % (tab_id, exc))
            continue
        if result.returncode == 0:
            log("renamed %s -> %r" % (tab_id, title))
        else:
            log("rename failed for %s: %s" % (tab_id, result.stderr.strip()))


def main():
    lock = acquire_lock(os.path.join(state_dir(), "daemon.pid"))
    if lock is None:
        log("title-sync daemon already running, exiting")
        return 0
    bin_path = herdr_bin()
    log("title-sync daemon started (pid %d)" % os.getpid())
    failures = 0
    while True:
        time.sleep(POLL_SECONDS)
        try:
            run_cycle(bin_path)
            failures = 0
        except Exception as exc:
            failures += 1
            log("cycle failed (%d/%d): %s" % (failures, MAX_LIST_FAILURES, exc))
            if failures >= MAX_LIST_FAILURES:
                log("herdr unreachable, exiting")
                return 1


if __name__ == "__main__":
    sys.exit(main())
