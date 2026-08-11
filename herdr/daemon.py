#!/usr/bin/env python3
"""Mirror agent terminal titles onto herdr tab labels."""

import json
import os


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
