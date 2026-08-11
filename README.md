# herdr-title-sync

A [herdr](https://herdr.dev) plugin that mirrors each agent's terminal title — the OSC title
Claude Code and other coding agents set to describe their current work — onto the herdr tab
label hosting that agent.

In a plain terminal the tab title follows the agent's title automatically. Herdr captures the
title per pane but keeps its own short tab labels ("1", "7"), so a wall of agent tabs is
unreadable. This plugin closes that gap.

## How it works

A `[[startup]]` daemon (`herdr/daemon.py`, python3, stdlib only) polls `herdr agent list` and
`herdr tab list` every 2 seconds and applies `herdr tab rename` wherever a tab's label differs
from its agent's `terminal_title_stripped`. Details:

- The plugin always wins: manual renames of a tab hosting an agent are overwritten within one
  poll cycle. Tabs without agents are never touched.
- Generic titles ("Claude Code") are mirrored too; only empty titles are skipped.
- When a tab hosts several agents, the first one with a non-empty title wins.
- A tab keeps its last mirrored name after its agent exits.
- A pidfile lock in the plugin state directory guarantees a single daemon instance.
- If herdr becomes unreachable (5 consecutive failed cycles), the daemon exits.

## Install

```sh
herdr plugin install elKei24/herdr-title-sync
```

Requires `python3` on `PATH` and herdr ≥ 0.8.0.

For local development, link a checkout instead:

```sh
herdr plugin link /path/to/herdr-title-sync
```

The startup hook fires when the herdr server starts, not at link/install time (verified on
herdr 0.8.0 — `plugin link`, `plugin enable`, and `server reload-config` do not trigger it).
Until the next server restart, start the daemon by hand:

```sh
HERDR_BIN_PATH="$(command -v herdr)" nohup python3 herdr/daemon.py >/dev/null 2>&1 &
```

## Uninstall

```sh
herdr plugin uninstall elkei24.title-sync
```

## Logs and troubleshooting

```sh
herdr plugin log list --plugin elkei24.title-sync
```

The daemon logs each rename and each failed cycle to stdout.

## Tests

```sh
python3 -m unittest discover -s tests -t . -v
```
